"""Home screen summary: what is on the accounts, what still goes off before the
next salary, what is left – and the net worth by kind.

Spending accounts ("Konten"): giro and PayPal with a bank balance in EUR.

Available until the next salary =
      balance of the spending accounts today
    + pending bookings the balance does not include yet
    + every expected booking on those accounts until the day before the
      next salary (fixed costs, card settlement, savings plan, other income)

Uses the balance forecast (core.forecast) with the end date set to the day
before the next salary. Credit card settlements are always included, also
when they fall after the salary: the money is already spent. The next salary is the next date of the recurring
income in category "Gehalt" (largest one if several); without it, the end of
the budget period. Transfers between two spending accounts cancel out.

Net worth by kind: spending accounts, credit cards (what they owe),
investments (depot, broker cash) and other accounts (savings, manual).
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Optional

from . import categories as cat
from . import recurring
from .forecast import _balance_type, card_settlements, forecast, pending_sum
from .recurring import load_pending
from .fx import Rates
from .reports import PENDING_BALANCE_TYPES, account_balances, calendar

SPENDING_KINDS = ("giro", "paypal")
GROUPS = [
    ("spending", "Konten", ("giro", "paypal")),
    ("cards", "Kreditkarten", ("card",)),
    ("investments", "Depot und Wertpapiere", ("depot", "broker")),
    ("other", "Sparen und Sonstiges", ("savings", "other")),
]


def next_salary(conn: sqlite3.Connection, today: date) -> Optional[dict]:
    salary_ids = {r[0] for r in conn.execute("SELECT id FROM categories WHERE name=?", (cat.SALARY,))}
    rejected = {k for k, v in recurring.decisions(conn).items() if v == "rejected"}
    booked = recurring.load_bookings(conn, today - timedelta(days=800), ("income",))
    found = [r for r in recurring.detect(booked, today, ("income",))
             if r.key not in rejected and r.category_id in salary_ids]
    if not found:
        return None
    r = max(found, key=lambda r: r.amount)
    return {"date": max(r.next_date, today), "amount": r.amount, "name": r.name, "overdue": r.next_date < today}


def summary(conn: sqlite3.Connection, today: date) -> dict:
    salary = next_salary(conn, today)
    if salary:
        until = max(today, salary["date"] - timedelta(days=1))
    else:
        until = calendar(conn).period_for(today).end
    fc = forecast(conn, today, until)
    spending = [a for a in fc["accounts"] if a["kind"] in SPENDING_KINDS]
    ids = {a["id"] for a in spending}

    balance = sum(a["balance"] for a in spending)
    lines: list[dict] = []
    pending = sum(a["pending"] for a in spending)
    if pending:
        lines.append({"kind": "pending", "label": "Vorgemerkt", "amount": pending, "date": None})
    # credit cards: what is spent on them is always deducted, even when the
    # settlement comes after the salary
    all_pending = load_pending(conn)
    settlements, _ = card_settlements(conn, today, all_pending)
    for acc_id, items in settlements.items():
        if acc_id not in ids:
            continue
        for e in items:
            card_id = int(e.key.split(":", 1)[1])
            # part of the settlement the card's booked balance does not show yet
            card_pending = -pending_sum(all_pending.get(card_id, []),
                                        _balance_type(conn, card_id) in PENDING_BALANCE_TYPES)
            lines.append({"kind": "card", "label": e.name, "amount": e.amount, "date": e.date.isoformat(),
                          "overdue": e.overdue, "pending": card_pending})
    # one line per expected booking; transfers between two spending accounts cancel out
    for key, items in _by_key(spending).items():
        if key.startswith("card:"):
            continue                      # taken from the settlements above
        total = sum(e["amount"] for e in items)
        if not total:
            continue
        first = min(items, key=lambda e: e["date"])
        kind = "income" if total > 0 else "fixed"
        lines.append({"kind": kind, "label": first["name"], "amount": total, "date": first["date"],
                      "overdue": first["overdue"]})
    lines.sort(key=lambda l: (l["date"] or "", l["amount"]))

    return {
        "today": today.isoformat(),
        "until": until.isoformat(),
        "salary": ({"date": salary["date"].isoformat(), "amount": salary["amount"], "name": salary["name"],
                    "overdue": salary["overdue"]} if salary else None),
        "accounts": [{"id": a["id"], "name": a["name"], "balance": a["balance"], "color_slot": a["color_slot"]}
                     for a in spending],
        "balance": balance,
        "lines": lines,
        "outgoing": sum(l["amount"] for l in lines if l["amount"] < 0),
        "incoming": sum(l["amount"] for l in lines if l["amount"] > 0),
        "available": balance + sum(l["amount"] for l in lines),
        "net_worth": net_worth_by_kind(conn, today, ids),
    }


def _by_key(accounts: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for a in accounts:
        for e in a["expected"]:
            out.setdefault(e["key"], []).append(e)
    return out


def net_worth_by_kind(conn: sqlite3.Connection, today: date, spending_ids: set[int]) -> dict:
    rates = Rates(conn)
    balances = account_balances(conn, [today])
    groups = {g: {"key": g, "label": label, "amount": 0, "accounts": []} for g, label, _ in GROUPS}
    kind_to_group = {k: g for g, _, kinds in GROUPS for k in kinds}
    not_converted = 0
    for a in conn.execute("SELECT id, name, kind, currency, color_slot FROM accounts WHERE hidden=0 ORDER BY sort, id"):
        value = balances[a["id"]][today]
        if value is None:
            continue
        eur = rates.to_eur(value, a["currency"], today)
        if eur is None:
            not_converted += 1
            continue
        g = groups[kind_to_group.get(a["kind"], "other")]
        g["amount"] += eur
        g["accounts"].append({"id": a["id"], "name": a["name"], "amount": eur, "color_slot": a["color_slot"]})
    parts = [g for g in groups.values() if g["accounts"]]
    return {"total": sum(g["amount"] for g in parts), "parts": parts, "not_converted": not_converted}
