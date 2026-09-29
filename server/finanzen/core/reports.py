"""Figures for the app. All sums in EUR minor units, computed from tx_derived.

- Ausgaben: -sum(expense); refunds are positive expenses and reduce it.
- Einnahmen: sum(income).
- Sparquote: (Einnahmen - Ausgaben) / Einnahmen.
- Übrig: Einnahmen - Ausgaben - Fixkosten, die bis zum Ende des Zeitraums
  noch erwartet werden + erwartete regelmäßige Einnahmen (nur im laufenden
  Zeitraum). Übrig pro Tag: Übrig / verbleibende Tage.
- Vergleich: previous period up to the same day offset.
- Durchschnitt je Kategorie: sum over the last 12 periods before the shown
  one, divided by the number of those periods. Only periods that start on
  or after the first booking count, so a short history is not diluted.
- Vermögen: balances in EUR; a past day's balance is the latest balance minus
  the bookings since. Pending only if the balance type includes them.
  PayPal purchases paid directly by the bank do not move the PayPal balance.
- Periods filter on tx_derived.budget_date (booking date, salary shifted
  to the next month in calendar mode), see periods.budget_day.
- Foreign amounts without a rate are left out and counted as not converted.
"""

from __future__ import annotations

import sqlite3
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

from . import recurring
from .db import get_setting
from .fx import Rates
from .periods import Period, PeriodCalendar, budget_day

PENDING_BALANCE_TYPES = {"XPCD", "ITAV", "CLAV", "XPAV"}


def salary_day(conn: sqlite3.Connection) -> Optional[int]:
    """Setting salary_day: a day (salary-to-salary periods) or empty/0 (calendar months, default)."""
    raw = get_setting(conn, "salary_day", "0")
    return int(raw) if raw and raw.isdigit() and int(raw) > 0 else None


def calendar(conn: sqlite3.Connection) -> PeriodCalendar:
    rows = conn.execute("""SELECT t.booking_date FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
                           JOIN categories c ON c.id=d.category_id
                           WHERE d.role='income' AND c.name='Gehalt'""")
    return PeriodCalendar(salary_day(conn), [date.fromisoformat(r[0]) for r in rows])


def period_dict(p: Period) -> dict:
    return {"key": p.key, "label": p.label, "start": p.start.isoformat(), "end": p.end.isoformat(),
            "days": p.days}


def _account_filter(account_ids: Optional[Iterable[int]], alias: str = "t") -> tuple[str, list]:
    ids = list(account_ids or [])
    if not ids:
        return "", []
    return f" AND {alias}.account_id IN ({','.join('?' * len(ids))})", ids


@dataclass
class Sums:
    spent: int = 0
    income: int = 0
    not_converted: int = 0
    pending: int = 0


def sums(conn: sqlite3.Connection, start: date, end: date,
         account_ids: Optional[Iterable[int]] = None) -> Sums:
    where, args = _account_filter(account_ids)
    row = conn.execute(f"""
        SELECT
          COALESCE(-SUM(CASE WHEN d.role='expense' THEN d.amount_eur_minor END), 0) AS spent,
          COALESCE(SUM(CASE WHEN d.role='income' THEN d.amount_eur_minor END), 0) AS income,
          SUM(CASE WHEN d.role IN ('expense','income') AND d.amount_eur_minor IS NULL THEN 1 ELSE 0 END) AS nc,
          SUM(CASE WHEN d.role IN ('expense','income') AND t.status='pending' THEN 1 ELSE 0 END) AS pending
        FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
        WHERE d.budget_date BETWEEN ? AND ? {where}""",
                       [start.isoformat(), end.isoformat(), *args]).fetchone()
    return Sums(row["spent"], row["income"], row["nc"] or 0, row["pending"] or 0)


def by_category(conn: sqlite3.Connection, start: date, end: date,
                account_ids: Optional[Iterable[int]] = None, role: str = "expense") -> list[dict]:
    where, args = _account_filter(account_ids, "l")
    sign = -1 if role == "expense" else 1
    # tx_lines: whole transactions, or their item lines when split (online orders)
    rows = conn.execute(f"""
        SELECT c.id, c.name, c.color_slot, {sign} * SUM(l.amount_eur_minor) AS amount, COUNT(*) AS n
        FROM tx_lines l JOIN categories c ON c.id=l.category_id
        WHERE l.role=? AND l.amount_eur_minor IS NOT NULL AND l.budget_date BETWEEN ? AND ? {where}
        GROUP BY c.id ORDER BY amount DESC""",
                        [role, start.isoformat(), end.isoformat(), *args]).fetchall()
    return [dict(r) for r in rows if r["amount"]]


def by_account(conn: sqlite3.Connection, start: date, end: date) -> list[dict]:
    rows = conn.execute("""
        SELECT a.id, a.name, a.kind, a.color_slot, -SUM(d.amount_eur_minor) AS amount, COUNT(*) AS n
        FROM transactions t JOIN tx_derived d ON d.tx_id=t.id JOIN accounts a ON a.id=t.account_id
        WHERE d.role='expense' AND d.amount_eur_minor IS NOT NULL AND d.budget_date BETWEEN ? AND ?
        GROUP BY a.id ORDER BY amount DESC""", (start.isoformat(), end.isoformat())).fetchall()
    return [dict(r) for r in rows if r["amount"]]


def category_averages(conn: sqlite3.Connection, cal: PeriodCalendar, period: Period,
                      account_ids: Optional[Iterable[int]] = None, n: int = 12) -> tuple[list[Period], dict[int, int]]:
    first = conn.execute("SELECT MIN(booking_date) FROM transactions").fetchone()[0]
    if not first:
        return [], {}
    periods: list[Period] = []
    p = cal.previous(period)
    while len(periods) < n and p.start >= date.fromisoformat(first):
        periods.append(p)
        p = cal.previous(p)
    if not periods:
        return [], {}
    totals = by_category(conn, periods[-1].start, periods[0].end, account_ids)
    return periods, {c["id"]: round(c["amount"] / len(periods)) for c in totals}


def overview(conn: sqlite3.Connection, period: Period, today: date,
             account_ids: Optional[Iterable[int]] = None) -> dict:
    cal = calendar(conn)
    ids = list(account_ids or [])
    cutoff = min(today, period.end)
    current = sums(conn, period.start, period.end, ids)
    prev = cal.previous(period)
    offset = (cutoff - period.start).days
    prev_cutoff = min(prev.start + timedelta(days=offset), prev.end)
    prev_same_day = sums(conn, prev.start, prev_cutoff, ids)
    prev_full = sums(conn, prev.start, prev.end, ids)
    avg_periods, averages = category_averages(conn, cal, period, ids)
    categories = [{**c, "average": averages.get(c["id"])} for c in by_category(conn, period.start, period.end, ids)]
    return {
        "period": period_dict(period),
        "today": today.isoformat(),
        "spent": current.spent,
        "income": current.income,
        "savings_rate": round((current.income - current.spent) / current.income, 4) if current.income > 0 else None,
        "previous": {"period": period_dict(prev), "spent_same_day": prev_same_day.spent,
                     "spent": prev_full.spent, "income": prev_full.income, "cutoff": prev_cutoff.isoformat()},
        "budget": budget(conn, period, today, current, ids),
        "not_converted": current.not_converted,
        "pending": current.pending,
        "categories": categories,
        "average_periods": len(avg_periods),
        "cards": by_account(conn, period.start, period.end),
        "trend": trend(conn, cal, period, 12, ids),
    }


def budget(conn: sqlite3.Connection, period: Period, today: date, s: Sums,
           account_ids: Optional[Iterable[int]] = None) -> dict:
    current = period.contains(today)
    days_left = max(0, (period.end - today).days + 1) if current else 0
    expected = recurring.upcoming(conn, today, period.end, list(account_ids or [])) if current else []
    # a salary expected at the end of the month counts for the next one (calendar months)
    salary_ids = {r[0] for r in conn.execute("SELECT id FROM categories WHERE name='Gehalt'")}
    calendar_months = salary_day(conn) is None
    expected = [e for e in expected
                if budget_day(e.date, e.role == "income" and e.category_id in salary_ids, calendar_months)
                <= period.end]
    fixed = sum(e.amount for e in expected if e.role == "expense")
    income = sum(e.amount for e in expected if e.role == "income")
    remaining = s.income - s.spent + fixed + income
    return {"period": period_dict(period), "income": s.income, "spent": s.spent,
            "fixed_expected": fixed, "income_expected": income, "remaining": remaining,
            "days_left": days_left, "per_day": remaining // days_left if days_left else None}


def trend(conn: sqlite3.Connection, cal: PeriodCalendar, last: Period, n: int,
          account_ids: Optional[Iterable[int]] = None) -> list[dict]:
    periods = [last]
    for _ in range(n - 1):
        periods.insert(0, cal.previous(periods[0]))
    out = []
    for p in periods:
        s = sums(conn, p.start, p.end, account_ids)
        out.append({**period_dict(p), "spent": s.spent, "income": s.income})
    return out


# --- balances and net worth ---------------------------------------------------------

def _paypal_bank_funded(conn: sqlite3.Connection) -> set[int]:
    return {r[0] for r in conn.execute("SELECT b_id FROM links WHERE kind='paypal' AND b_id IS NOT NULL")}


def account_balances(conn: sqlite3.Connection, days: list[date]) -> dict[int, dict[date, Optional[int]]]:
    """Balance of every account (own currency, minor units) at the end of each day."""
    skip = _paypal_bank_funded(conn)
    out: dict[int, dict[date, Optional[int]]] = {}
    for acc in conn.execute("SELECT * FROM accounts"):
        snaps = conn.execute(
            """SELECT * FROM balances WHERE account_id=? ORDER BY as_of DESC, fetched_at DESC""",
            (acc["id"],)).fetchall()
        series: dict[date, Optional[int]] = {}
        if not snaps:
            out[acc["id"]] = {d: None for d in days}
            continue
        if acc["source"] == "api":
            latest = snaps[0]
            as_of = date.fromisoformat(latest["as_of"])
            with_pending = latest["balance_type"] in PENDING_BALANCE_TYPES
            txs = conn.execute(
                """SELECT id, booking_date, amount_minor, status FROM transactions
                   WHERE account_id=? AND removed_at IS NULL AND source != 'wallet'
                   AND currency=?""", (acc["id"], acc["currency"])).fetchall()
            for d in days:
                if d >= as_of:
                    series[d] = latest["amount_minor"]
                    continue
                since = sum(t["amount_minor"] for t in txs
                            if t["id"] not in skip and d.isoformat() < t["booking_date"] <= as_of.isoformat()
                            and (t["status"] == "booked" or with_pending))
                series[d] = latest["amount_minor"] - since
        else:
            # manual / imported snapshots (depot value, card debt): last known value
            ordered = sorted(snaps, key=lambda s: s["as_of"])
            dates = [s["as_of"] for s in ordered]
            for d in days:
                i = bisect_right(dates, d.isoformat()) - 1
                series[d] = ordered[i]["amount_minor"] if i >= 0 else None
        out[acc["id"]] = series
    return out


def net_worth(conn: sqlite3.Connection, days: list[date]) -> list[dict]:
    rates = Rates(conn)
    currencies = {r["id"]: r["currency"] for r in conn.execute("SELECT id, currency FROM accounts")}
    balances = account_balances(conn, days)
    out = []
    for d in days:
        total, missing = 0, 0
        for acc_id, series in balances.items():
            value = series.get(d)
            if value is None:
                continue
            eur = rates.to_eur(value, currencies[acc_id], d)
            if eur is None:
                missing += 1
            else:
                total += eur
        out.append({"date": d.isoformat(), "value": total, "not_converted": missing})
    return out


RANGES = {"1M": 31, "3M": 92, "6M": 183, "1J": 366, "3J": 1096}


def net_worth_series(conn: sqlite3.Connection, today: date, range_key: str = "1J") -> list[dict]:
    if range_key in RANGES:
        start = today - timedelta(days=RANGES[range_key])
    else:
        first = conn.execute("SELECT MIN(booking_date) FROM transactions").fetchone()[0]
        start = date.fromisoformat(first) if first else today - timedelta(days=30)
    span = (today - start).days
    step = 1 if span <= 92 else (7 if span <= 400 else 14)
    days = [start + timedelta(days=i) for i in range(0, span, step)] + [today]
    return net_worth(conn, days)


def accounts_summary(conn: sqlite3.Connection, today: date) -> list[dict]:
    rates = Rates(conn)
    balances = account_balances(conn, [today])
    out = []
    for a in conn.execute("""SELECT a.*, c.status AS connection_status, c.valid_until, c.last_sync_at,
                                    c.institution AS connection_institution
                             FROM accounts a LEFT JOIN connections c ON c.id=a.connection_id
                             WHERE a.hidden=0 ORDER BY a.sort"""):
        value = balances[a["id"]][today]
        out.append({
            "id": a["id"], "name": a["name"], "kind": a["kind"], "currency": a["currency"],
            "institution": a["institution"], "source": a["source"], "color_slot": a["color_slot"],
            "iban": mask_iban(a["iban"]), "patterns": a["patterns"],
            "balance": value, "balance_eur": rates.to_eur(value, a["currency"], today) if value is not None else None,
            "connection_status": a["connection_status"], "valid_until": a["valid_until"],
            "last_sync_at": a["last_sync_at"],
        })
    return out


def mask_iban(iban: Optional[str]) -> Optional[str]:
    if not iban:
        return None
    compact = iban.replace(" ", "")
    return f"{compact[:4]} •••• {compact[-4:]}"


# --- explore (Sankey) ---------------------------------------------------------------

def sankey(conn: sqlite3.Connection, start: date, end: date) -> dict:
    """Income forms one pot and flows proportionally to the accounts where money
    was spent; accounts flow to categories. Transfers are left out. The bank
    data does not say which money paid for what."""
    income = by_category(conn, start, end, role="income")
    total_income = sum(c["amount"] for c in income)
    rows = conn.execute("""
        SELECT a.id AS account_id, a.name AS account, a.color_slot AS account_slot,
               c.id AS category_id, c.name AS category, c.color_slot AS category_slot,
               -SUM(l.amount_eur_minor) AS amount
        FROM tx_lines l
        JOIN accounts a ON a.id=l.account_id JOIN categories c ON c.id=l.category_id
        WHERE l.role='expense' AND l.amount_eur_minor IS NOT NULL AND l.budget_date BETWEEN ? AND ?
        GROUP BY a.id, c.id HAVING amount > 0""", (start.isoformat(), end.isoformat())).fetchall()
    spent_by_account: dict[int, int] = {}
    for r in rows:
        spent_by_account[r["account_id"]] = spent_by_account.get(r["account_id"], 0) + r["amount"]
    total_spent = sum(spent_by_account.values())

    nodes: list[dict] = []
    links: list[dict] = []

    def node(node_id: str, label: str, column: int, kind: str, slot=None) -> str:
        if not any(n["id"] == node_id for n in nodes):
            nodes.append({"id": node_id, "label": label, "column": column, "kind": kind, "color_slot": slot})
        return node_id

    for c in income:
        links.append({"source": node(f"in:{c['id']}", c["name"], 0, "income"),
                      "target": node("pot", "Einnahmen", 1, "pot"), "value": c["amount"]})
    shortfall = max(0, total_spent - total_income)
    if shortfall:
        links.append({"source": node("savings", "Aus Guthaben", 0, "savings"),
                      "target": node("pot", "Einnahmen", 1, "pot"), "value": shortfall})
    names = {r["account_id"]: (r["account"], r["account_slot"]) for r in rows}
    for acc_id, amount in sorted(spent_by_account.items(), key=lambda kv: -kv[1]):
        links.append({"source": node("pot", "Einnahmen", 1, "pot"),
                      "target": node(f"acc:{acc_id}", names[acc_id][0], 2, "account", names[acc_id][1]),
                      "value": amount})
    for r in sorted(rows, key=lambda r: -r["amount"]):
        links.append({"source": f"acc:{r['account_id']}",
                      "target": node(f"cat:{r['category_id']}", r["category"], 3, "category", r["category_slot"]),
                      "value": r["amount"]})
    left = total_income - total_spent
    if left > 0:
        links.append({"source": node("pot", "Einnahmen", 1, "pot"),
                      "target": node("left", "Übrig", 2, "left"), "value": left})
    return {"nodes": nodes, "links": links, "income": total_income, "spent": total_spent,
            "start": start.isoformat(), "end": end.isoformat()}
