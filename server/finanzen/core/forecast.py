"""Balance forecast per account until the end of the budget period.

Forecast = balance today
         + pending bookings the balance does not include yet (Apple Pay
           notifications always, bank pending unless the balance type has them)
         + every expected recurring booking up to the end date
           (expenses, income and recurring transfers such as a savings plan).

An expected booking is skipped when a booking of the same payee already
stands for it within the interval tolerance: a pending one, or a booked one
with a different amount (a card bill after a holiday month). Overdue bookings
still count. Only EUR accounts with a bank balance are forecast; payees
the user marked as "not recurring" are left out.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from . import recurring
from .recurring import INTERVALS, Booking, Recurring, group_key, next_after
from .reports import PENDING_BALANCE_TYPES, account_balances, calendar

ROLES = ("expense", "income", "transfer")


@dataclass
class Expected:
    date: date
    name: str
    amount: int
    role: str
    interval: str
    key: str
    overdue: bool


def occurrences(r: Recurring, today: date, until: date, seen: list[Booking]) -> list[Expected]:
    """Expected bookings of one series; `seen` are this account's other
    bookings (pending, and booked ones outside the series)."""
    tol = INTERVALS[r.interval][1]
    ids = set(r.tx_ids)
    out = []
    day = r.next_date
    while day <= until:
        covered = any(b.id not in ids and b.date > r.last_date and group_key(b) == r.key
                      and abs((b.date - day).days) <= tol for b in seen)
        if not covered:
            out.append(Expected(day, r.name, r.amount, r.role, r.interval, r.key, day < today))
        day = next_after(day, r.interval)
    return out


def project(balance: int, pending: list[Booking], pending_in_balance: bool,
            items: list[Recurring], today: date, until: date, booked: list[Booking] = ()) -> dict:
    """Pure part: one account's forecast and its lowest point."""
    seen = [*pending, *booked]
    expected = sorted((e for r in items for e in occurrences(r, today, until, seen)),
                      key=lambda e: (e.date, e.amount))
    # Apple Pay notifications are never in the bank's balance yet
    pending_sum = sum(p.amount_eur for p in pending if not pending_in_balance or p.source == "wallet")
    running = balance + pending_sum
    low, low_date = running, today
    for e in expected:
        running += e.amount
        if running < low:
            low, low_date = running, max(e.date, today)
    return {"balance": balance, "pending": pending_sum, "expected": expected,
            "forecast": running, "lowest": low, "lowest_date": low_date}


def _pending(conn: sqlite3.Connection) -> dict[int, list[Booking]]:
    out: dict[int, list[Booking]] = {}
    for r in conn.execute("""
            SELECT t.id, t.account_id, t.booking_date, t.amount_minor, t.counterparty, t.description,
                   t.source, d.role, d.category_id
            FROM transactions t JOIN tx_derived d ON d.tx_id=t.id JOIN accounts a ON a.id=t.account_id
            WHERE t.status='pending' AND t.removed_at IS NULL
              AND d.role != 'excluded' AND t.currency=a.currency"""):
        out.setdefault(r["account_id"], []).append(
            Booking(r["id"], r["account_id"], date.fromisoformat(r["booking_date"]), r["amount_minor"],
                    r["role"], r["counterparty"] or "", r["description"] or "", r["category_id"], r["source"]))
    return out


def forecast(conn: sqlite3.Connection, today: date, until: Optional[date] = None) -> dict:
    if until is None:
        until = calendar(conn).period_for(today).end
    rejected = {k for k, v in recurring.decisions(conn).items() if v == "rejected"}
    booked = recurring.load_bookings(conn, today - timedelta(days=800), ROLES)
    found = [r for r in recurring.detect(booked, today, ROLES) if r.key not in rejected]
    recent = [b for b in booked if b.date >= today - timedelta(days=400)]
    pending = _pending(conn)
    balances = account_balances(conn, [today])
    accounts = []
    for a in conn.execute("""SELECT id, name, kind, color_slot FROM accounts
                             WHERE source='api' AND hidden=0 AND currency='EUR' ORDER BY sort, id"""):
        balance = balances[a["id"]][today]
        if balance is None:
            continue
        latest = conn.execute("SELECT balance_type FROM balances WHERE account_id=? "
                              "ORDER BY as_of DESC, fetched_at DESC LIMIT 1", (a["id"],)).fetchone()
        p = project(balance, pending.get(a["id"], []), latest["balance_type"] in PENDING_BALANCE_TYPES,
                    [r for r in found if r.account_id == a["id"]], today, until,
                    [b for b in recent if b.account_id == a["id"]])
        accounts.append({
            "id": a["id"], "name": a["name"], "kind": a["kind"], "color_slot": a["color_slot"],
            "balance": p["balance"], "pending": p["pending"], "forecast": p["forecast"],
            "lowest": p["lowest"], "lowest_date": p["lowest_date"].isoformat(),
            "expected": [{"date": e.date.isoformat(), "name": e.name, "amount": e.amount, "role": e.role,
                          "interval": e.interval, "key": e.key, "overdue": e.overdue} for e in p["expected"]],
        })
    return {
        "today": today.isoformat(), "until": until.isoformat(), "accounts": accounts,
        "balance": sum(a["balance"] for a in accounts),
        "forecast": sum(a["forecast"] for a in accounts),
    }
