"""Recurring payments (Fixkosten): bookings that repeat at a steady interval
with a steady amount.

Detection (pure function over booked rows; expense and income for the
Fixkosten list, plus transfers for the balance forecast):
1. Group by account, direction and payee (counterparty, else the booking
   text without digits).
2. Within a group, cluster by amount: in date order, a booking joins the
   cluster whose latest amount is within 25 %. So a salary and a holiday
   bonus from the same employer stay apart, and a price change stays in
   its series.
3. A cluster is recurring when at least 75 % of the gaps between bookings
   match one interval (weekly, monthly, quarterly, half-yearly, yearly) and
   there are enough bookings (3 for weekly and monthly, 2 otherwise). Two
   bookings only count when the payee got nothing else and the amount
   stayed within 5 %.
4. It is still active unless the next booking is overdue by more than one
   interval.

Expected amount: median of the last three bookings; after a steady amount
changes, the new amount (price change, reported with the old one). The user can mark a
payee as "not recurring"; that decision is stored by key and survives
every recomputation.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from statistics import median
from typing import Optional

from .categories import fold
from .db import utcnow

# name -> (nominal days, tolerance in days, months per step or None, per year)
INTERVALS: dict[str, tuple[int, int, Optional[int], float]] = {
    "weekly": (7, 2, None, 52),
    "monthly": (30, 5, 1, 12),
    "quarterly": (91, 12, 3, 4),
    "halfyearly": (182, 15, 6, 2),
    "yearly": (365, 20, 12, 1),
}
MIN_COUNT = {"weekly": 3, "monthly": 3}
AMOUNT_TOLERANCE = 0.25
SPARSE_TOLERANCE = 0.05               # series with fewer than 3 bookings
GAP_SHARE = 0.75


@dataclass
class Booking:
    id: int
    account_id: int
    date: date
    amount_eur: int
    role: str                         # expense | income | transfer
    counterparty: str = ""
    description: str = ""
    category_id: Optional[int] = None
    source: str = ""                  # api | import | wallet | manual


@dataclass
class Recurring:
    key: str                          # stable id for user decisions
    account_id: int
    name: str
    role: str
    interval: str
    amount: int                       # expected, signed EUR minor units
    previous_amount: Optional[int]    # amount before the latest change, if any
    last_date: date
    next_date: date
    count: int
    category_id: Optional[int]
    tx_ids: list[int] = field(default_factory=list)

    @property
    def monthly(self) -> int:
        """Amount spread over a month (a yearly bill counts 1/12)."""
        return round(self.amount * INTERVALS[self.interval][3] / 12)


def payee(b: Booking) -> str:
    """Display name: counterparty, else the booking text."""
    return (b.counterparty or b.description).strip()


def payee_key(b: Booking) -> str:
    text = fold(b.counterparty or b.description)
    text = re.sub(r"[^A-Z& ]+", " ", text)          # drop digits and punctuation
    return re.sub(r"\s+", " ", text).strip()


def group_key(b: Booking) -> str:
    sign = "+" if b.amount_eur > 0 else "-"
    return f"{b.account_id}:{sign}:{payee_key(b)}"


def _clusters(bookings: list[Booking]) -> list[list[Booking]]:
    """In date order, a booking joins the cluster whose latest amount is
    closest and within the tolerance; so prices may creep up over time."""
    clusters: list[list[Booking]] = []
    for b in sorted(bookings, key=lambda b: (b.date, b.id)):
        best, best_diff = None, None
        for c in clusters:
            last = abs(c[-1].amount_eur)
            diff = abs(abs(b.amount_eur) - last)
            if diff <= AMOUNT_TOLERANCE * last and (best_diff is None or diff < best_diff):
                best, best_diff = c, diff
        if best is None:
            clusters.append([b])
        else:
            best.append(b)
    return clusters


def _interval(dates: list[date]) -> Optional[str]:
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    if not gaps:
        return None
    for name, (days, tol, _, _) in INTERVALS.items():
        if len(dates) < MIN_COUNT.get(name, 2):
            continue
        hits = sum(1 for g in gaps if abs(g - days) <= tol)
        if hits / len(gaps) >= GAP_SHARE:
            return name
    return None


def _clear_pair(cluster: list[Booking], members: list[Booking]) -> bool:
    """Two bookings a year apart only count when nothing else went to that
    payee and the amount barely changed (not two holidays at the same shop)."""
    amounts = [abs(b.amount_eur) for b in cluster]
    return len(members) == len(cluster) and max(amounts) - min(amounts) <= SPARSE_TOLERANCE * max(amounts)


def add_months(day: date, months: int) -> date:
    y, m = divmod(day.month - 1 + months, 12)
    year, month = day.year + y, m + 1
    for d in (day.day, 30, 29, 28):
        try:
            return date(year, month, d)
        except ValueError:
            continue
    raise AssertionError("unreachable")


def next_after(day: date, interval: str) -> date:
    days, _, months, _ = INTERVALS[interval]
    return add_months(day, months) if months else day + timedelta(days=days)


def expected_amount(amounts: list[int]) -> tuple[int, Optional[int]]:
    """(expected, previous). A steady amount that changed with the latest
    booking is a price change: the new amount counts. Otherwise the median
    of the last three."""
    before = amounts[-4:-1]
    if len(before) >= 2 and len(set(before)) == 1 and amounts[-1] != before[0]:
        return amounts[-1], before[0]
    return int(median(amounts[-3:])), None


def detect(bookings: list[Booking], today: date,
           roles: tuple[str, ...] = ("expense", "income")) -> list[Recurring]:
    groups: dict[str, list[Booking]] = {}
    for b in bookings:
        if b.amount_eur == 0 or (b.role == "expense" and b.amount_eur > 0):
            continue                  # refunds are not recurring payments
        if b.role not in roles or not payee_key(b):
            continue
        groups.setdefault(group_key(b), []).append(b)

    out: list[Recurring] = []
    for key, members in groups.items():
        for cluster in _clusters(members):
            interval = _interval([b.date for b in cluster])
            if interval is None or (len(cluster) < 3 and not _clear_pair(cluster, members)):
                continue
            days, tol, _, _ = INTERVALS[interval]
            last = cluster[-1]
            nxt = next_after(last.date, interval)
            if (today - nxt).days > days + tol:
                continue              # ended
            amount, previous = expected_amount([b.amount_eur for b in cluster])
            out.append(Recurring(
                key=key, account_id=last.account_id, name=payee(last), role=last.role,
                interval=interval, amount=amount, previous_amount=previous,
                last_date=last.date, next_date=nxt, count=len(cluster),
                category_id=last.category_id, tx_ids=[b.id for b in cluster][-6:]))
    out.sort(key=lambda r: (r.role, r.monthly))
    return out


# --- database -------------------------------------------------------------------------

def load_bookings(conn: sqlite3.Connection, since: date,
                  roles: tuple[str, ...] = ("expense", "income")) -> list[Booking]:
    marks = ",".join("?" * len(roles))
    rows = conn.execute(f"""
        SELECT t.id, t.account_id, t.booking_date, t.counterparty, t.description,
               d.role, d.category_id, d.amount_eur_minor
        FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
        WHERE t.status='booked' AND t.removed_at IS NULL AND d.role IN ({marks})
          AND d.amount_eur_minor IS NOT NULL AND t.booking_date >= ?""", (*roles, since.isoformat()))
    return [Booking(r["id"], r["account_id"], date.fromisoformat(r["booking_date"]), r["amount_eur_minor"],
                    r["role"], r["counterparty"] or "", r["description"] or "", r["category_id"])
            for r in rows]


def decisions(conn: sqlite3.Connection) -> dict[str, str]:
    return {r["key"]: r["decision"] for r in conn.execute("SELECT key, decision FROM recurring_decisions")}


def decide(conn: sqlite3.Connection, key: str, decision: Optional[str]) -> None:
    if decision is None:
        conn.execute("DELETE FROM recurring_decisions WHERE key=?", (key,))
    elif decision == "rejected":
        conn.execute("INSERT OR REPLACE INTO recurring_decisions (key, decision, decided_at) VALUES (?,?,?)",
                     (key, decision, utcnow()))
    else:
        raise ValueError("invalid decision")


def overview(conn: sqlite3.Connection, today: date) -> dict:
    """Active recurring payments; rejected ones listed apart and left out of totals."""
    found = detect(load_bookings(conn, today - timedelta(days=800)), today)
    rejected = {k for k, v in decisions(conn).items() if v == "rejected"}
    cats = {r["id"]: r for r in conn.execute("SELECT id, name, color_slot FROM categories")}
    accs = {r["id"]: r for r in conn.execute("SELECT id, name, color_slot FROM accounts")}

    def as_json(r: Recurring) -> dict:
        c, a = cats.get(r.category_id), accs.get(r.account_id)
        return {
            "key": r.key, "name": r.name, "role": r.role, "interval": r.interval,
            "amount": r.amount, "previous_amount": r.previous_amount, "monthly": r.monthly,
            "last_date": r.last_date.isoformat(), "next_date": r.next_date.isoformat(),
            "overdue": r.next_date < today, "count": r.count, "tx_ids": r.tx_ids,
            "category": {"id": r.category_id, "name": c["name"] if c else None,
                         "color_slot": c["color_slot"] if c else None},
            "account": {"id": r.account_id, "name": a["name"] if a else None,
                        "color_slot": a["color_slot"] if a else None},
        }

    active = [r for r in found if r.key not in rejected]
    return {
        "items": [as_json(r) for r in active],
        "rejected": [as_json(r) for r in found if r.key in rejected],
        "monthly_expense": -sum(r.monthly for r in active if r.role == "expense"),
        "monthly_income": sum(r.monthly for r in active if r.role == "income"),
    }
