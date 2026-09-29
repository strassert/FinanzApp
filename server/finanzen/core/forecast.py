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

Credit cards: the open amount of the card is debited from the paying
account one month after the last settlement (settlement = transfer from
another account to the card, linked or matching the card's patterns).
Open amount = card balance plus what it does not include yet; for a card
without balance, the sum of all its bookings. Recurring transfers that are
card settlements are left out, so nothing counts twice.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Optional

from . import recurring
from .recurring import Booking, Expected, Recurring, add_months, load_pending, occurrences
from .reports import PENDING_BALANCE_TYPES, account_balances, calendar

ROLES = ("expense", "income", "transfer")
SETTLEMENT_GRACE = 5


def pending_sum(pending: list[Booking], pending_in_balance: bool) -> int:
    # Apple Pay notifications are never in the bank's balance yet
    return sum(p.amount_eur for p in pending if not pending_in_balance or p.source == "wallet")


def next_settlement(last: date, today: date) -> date:
    """One month after the last settlement; a few days late still counts as that one."""
    day = add_months(last, 1)
    while day < today - timedelta(days=SETTLEMENT_GRACE):
        day = add_months(day, 1)
    return day


def project(balance: int, pending: list[Booking], pending_in_balance: bool,
            items: list[Recurring], today: date, until: date, booked: list[Booking] = (),
            extra: list[Expected] = ()) -> dict:
    """Pure part: one account's forecast and its lowest point."""
    seen = [*pending, *booked]
    expected = sorted([*(e for r in items for e in occurrences(r, today, until, seen)),
                       *(e for e in extra if e.date <= until)],
                      key=lambda e: (e.date, e.amount))
    pending_total = pending_sum(pending, pending_in_balance)
    running = balance + pending_total
    low, low_date = running, today
    for e in expected:
        running += e.amount
        if running < low:
            low, low_date = running, max(e.date, today)
    return {"balance": balance, "pending": pending_total, "expected": expected,
            "forecast": running, "lowest": low, "lowest_date": low_date}


def _balance_type(conn: sqlite3.Connection, account_id: int) -> Optional[str]:
    row = conn.execute("SELECT balance_type FROM balances WHERE account_id=? "
                       "ORDER BY as_of DESC, fetched_at DESC LIMIT 1", (account_id,)).fetchone()
    return row["balance_type"] if row else None


def _card_open(conn: sqlite3.Connection, card: sqlite3.Row, today: date,
               pending: list[Booking]) -> int:
    """What the card owes today (positive), see module docstring."""
    snap = conn.execute("SELECT amount_minor, as_of, balance_type FROM balances WHERE account_id=? "
                        "ORDER BY as_of DESC, fetched_at DESC LIMIT 1", (card["id"],)).fetchone()
    base = """SELECT COALESCE(SUM(t.amount_minor), 0) FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
              WHERE t.account_id=? AND t.removed_at IS NULL AND d.role != 'excluded' AND t.currency=?
              AND t.source != 'wallet'"""
    wallet = sum(p.amount_eur for p in pending if p.source == "wallet")
    if snap is None:
        value = conn.execute(base, (card["id"], card["currency"])).fetchone()[0] + wallet
    elif card["source"] == "api":
        value = account_balances(conn, [today])[card["id"]][today]
        value += pending_sum(pending, snap["balance_type"] in PENDING_BALANCE_TYPES)
    else:
        value = snap["amount_minor"] + wallet + conn.execute(
            base + " AND t.booking_date > ?", (card["id"], card["currency"], snap["as_of"])).fetchone()[0]
    return max(0, -value)


def card_settlements(conn: sqlite3.Connection, today: date,
                     pending: dict[int, list[Booking]]) -> tuple[dict[int, list[Expected]], set[int]]:
    """Expected settlement per account, and the ids of all past settlement bookings."""
    extra: dict[int, list[Expected]] = {}
    ids: set[int] = set()
    for card in conn.execute("SELECT * FROM accounts WHERE kind='card' AND currency='EUR'").fetchall():
        patterns = [p.strip().upper() for p in (card["patterns"] or "").split(",") if p.strip()]
        found: list[tuple[date, int, int]] = []          # (date, payer account, tx id)
        for t in conn.execute("""
                SELECT t.id, t.account_id, t.booking_date, t.counterparty, t.description,
                       l.a_id, l.b_id, o.account_id AS other_account
                FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
                LEFT JOIN links l ON l.kind='transfer' AND (l.a_id=t.id OR l.b_id=t.id)
                LEFT JOIN transactions o ON o.id = CASE WHEN l.a_id=t.id THEN l.b_id ELSE l.a_id END
                WHERE d.role='transfer' AND t.amount_minor < 0 AND t.account_id != ?
                  AND t.removed_at IS NULL""", (card["id"],)):
            text = f"{t['counterparty'] or ''} {t['description'] or ''}".upper()
            if t["other_account"] == card["id"] or (t["other_account"] is None
                                                    and any(p in text for p in patterns)):
                found.append((date.fromisoformat(t["booking_date"]), t["account_id"], t["id"]))
                ids.add(t["id"])
                if t["a_id"] and t["b_id"]:
                    ids.update((t["a_id"], t["b_id"]))
        if not found:
            continue
        last, payer, _ = max(found)
        owed = _card_open(conn, card, today, pending.get(card["id"], []))
        if not owed:
            continue
        day = next_settlement(last, today)
        key = f"card:{card['id']}"
        extra.setdefault(payer, []).append(
            Expected(day, f"Abrechnung {card['name']}", -owed, "transfer", "monthly", key, day < today))
        extra.setdefault(card["id"], []).append(
            Expected(day, "Abrechnung", owed, "transfer", "monthly", key, day < today))
    return extra, ids


def forecast(conn: sqlite3.Connection, today: date, until: Optional[date] = None) -> dict:
    if until is None:
        until = calendar(conn).period_for(today).end
    rejected = {k for k, v in recurring.decisions(conn).items() if v == "rejected"}
    pending = load_pending(conn)
    settlements, settlement_ids = card_settlements(conn, today, pending)
    booked = recurring.load_bookings(conn, today - timedelta(days=800), ROLES)
    found = [r for r in recurring.detect(booked, today, ROLES)
             if r.key not in rejected and not settlement_ids.intersection(r.tx_ids)]
    recent = [b for b in booked if b.date >= today - timedelta(days=400)]
    balances = account_balances(conn, [today])
    accounts = []
    for a in conn.execute("""SELECT id, name, kind, color_slot FROM accounts
                             WHERE source='api' AND hidden=0 AND currency='EUR' ORDER BY sort, id"""):
        balance = balances[a["id"]][today]
        if balance is None:
            continue
        p = project(balance, pending.get(a["id"], []), _balance_type(conn, a["id"]) in PENDING_BALANCE_TYPES,
                    [r for r in found if r.account_id == a["id"]], today, until,
                    [b for b in recent if b.account_id == a["id"]], settlements.get(a["id"], []))
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
