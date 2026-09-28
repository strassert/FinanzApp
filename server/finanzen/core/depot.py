"""Depot value from broker exports and daily prices.

Holdings come from the broker's list of depot transactions (flatex
"Depotumsätze": one row per execution with the exact number of units). The
value of a depot on a day is the sum of units held x last known price, written
as a daily balance of type DEPOT, so reports treat it like any other account.

flatex books "Thesaurierung transparenter Fonds" (Austrian tax on accumulating
funds) as pairs that take every lot out and in again at the same quantity; they
change the tax base, not the holdings, and are skipped.

Prices: execution prices from the export, and daily closes fetched via
`update_quotes` for ISINs with a quote symbol in the config. Only EUR prices
are used.
"""

from __future__ import annotations

import json
import sqlite3
from bisect import bisect_right
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable, Optional

from ..money import to_minor

BALANCE_TYPE = "DEPOT"
QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?period1={start}&period2={end}&interval=1d"

_FLATEX_HEADERS = {"Buchungstag", "ISIN", "Nominal (Stk.)", "TA.-Nr.", "Buchungsinformation"}


@dataclass
class Trade:
    ext_id: str
    booking_date: date
    isin: str
    name: str
    quantity: Decimal
    amount_minor: Optional[int]
    currency: Optional[str]
    price: Optional[Decimal]


def is_flatex_depot(rows: list[list[str]]) -> bool:
    return bool(rows) and _FLATEX_HEADERS <= {c.strip() for c in rows[0]}


def parse_flatex_depot(rows: list[list[str]]) -> tuple[list[Trade], int]:
    """Rows of a flatex "Depotumsätze" CSV -> trades, number of skipped rows."""
    from .importer import parse_amount, parse_date

    header = [c.strip() for c in rows[0]]
    col = {name: header.index(name) for name in header if name}
    # Amount and price are followed by an unnamed currency column.
    cur_after = {name: col[name] + 1 for name in ("Betrag", "Kurs") if name in col}

    def cell(row, i):
        return row[i].strip() if i is not None and i < len(row) else ""

    trades, skipped = [], 0
    for row in rows[1:]:
        info = cell(row, col["Buchungsinformation"])
        if info.startswith("Thesaurierung"):
            skipped += 1
            continue
        day = parse_date(cell(row, col["Buchungstag"]))
        quantity = parse_amount(cell(row, col["Nominal (Stk.)"]))
        isin = cell(row, col["ISIN"]).upper()
        ext_id = cell(row, col["TA.-Nr."])
        if day is None or quantity is None or len(isin) != 12 or not ext_id:
            skipped += 1
            continue
        amount = parse_amount(cell(row, col.get("Betrag")))
        currency = cell(row, cur_after.get("Betrag")).upper() or None
        price = parse_amount(cell(row, col.get("Kurs")))
        price_currency = cell(row, cur_after.get("Kurs")).upper()
        trades.append(Trade(
            ext_id=ext_id, booking_date=day, isin=isin, name=cell(row, col.get("Bezeichnung")),
            quantity=quantity,
            amount_minor=to_minor(amount, currency) if amount is not None and currency else None,
            currency=currency,
            price=price if price_currency == "EUR" else None,
        ))
    return trades, skipped


def import_trades(conn: sqlite3.Connection, account_id: int, trades: list[Trade]) -> tuple[int, int]:
    """Store trades (known transaction numbers are skipped) -> (new, known)."""
    new = 0
    for t in trades:
        cur = conn.execute(
            """INSERT OR IGNORE INTO depot_trades (account_id, ext_id, booking_date, isin, name, quantity,
               amount_minor, currency) VALUES (?,?,?,?,?,?,?,?)""",
            (account_id, t.ext_id, t.booking_date.isoformat(), t.isin, t.name, str(t.quantity),
             t.amount_minor, t.currency))
        new += cur.rowcount
        if t.price is not None:
            # a fetched close for that day wins over the execution price
            conn.execute("""INSERT OR IGNORE INTO security_prices (isin, date, price, currency, source)
                            VALUES (?,?,?,?,'trade')""", (t.isin, t.booking_date.isoformat(), str(t.price), "EUR"))
    return new, len(trades) - new


def holdings(conn: sqlite3.Connection, account_id: int, day: date) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    for row in conn.execute("SELECT isin, quantity FROM depot_trades WHERE account_id=? AND booking_date<=?",
                            (account_id, day.isoformat())):
        out[row["isin"]] = out.get(row["isin"], Decimal(0)) + Decimal(row["quantity"])
    return {isin: q for isin, q in out.items() if q != 0}


def holdings_summary(conn: sqlite3.Connection, account_id: int, day: date) -> list[dict]:
    names = dict(conn.execute("SELECT isin, name FROM depot_trades WHERE account_id=? ORDER BY booking_date",
                              (account_id,)).fetchall())
    return [{"isin": isin, "name": names.get(isin, ""), "quantity": str(q)}
            for isin, q in sorted(holdings(conn, account_id, day).items())]


class _Prices:
    def __init__(self, conn: sqlite3.Connection):
        self._dates: dict[str, list[str]] = {}
        self._prices: dict[str, list[Decimal]] = {}
        for row in conn.execute("SELECT isin, date, price FROM security_prices WHERE currency='EUR' "
                                "ORDER BY isin, date"):
            self._dates.setdefault(row["isin"], []).append(row["date"])
            self._prices.setdefault(row["isin"], []).append(Decimal(row["price"]))

    def last(self, isin: str, day: date) -> Optional[Decimal]:
        dates = self._dates.get(isin, [])
        i = bisect_right(dates, day.isoformat()) - 1
        return self._prices[isin][i] if i >= 0 else None


def revalue(conn: sqlite3.Connection, account_id: int, today: date) -> int:
    """Rewrite the daily DEPOT balances from the first trade to today -> number of days."""
    trades = conn.execute("SELECT booking_date, isin, quantity FROM depot_trades WHERE account_id=? "
                          "ORDER BY booking_date", (account_id,)).fetchall()
    conn.execute("DELETE FROM balances WHERE account_id=? AND balance_type=?", (account_id, BALANCE_TYPE))
    if not trades:
        return 0
    prices = _Prices(conn)
    held: dict[str, Decimal] = {}
    i, day, days = 0, date.fromisoformat(trades[0]["booking_date"]), 0
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    while day <= today:
        while i < len(trades) and trades[i]["booking_date"] <= day.isoformat():
            held[trades[i]["isin"]] = held.get(trades[i]["isin"], Decimal(0)) + Decimal(trades[i]["quantity"])
            i += 1
        value = Decimal(0)
        for isin, qty in held.items():
            price = prices.last(isin, day)
            if qty and price is not None:
                value += qty * price
        conn.execute("""INSERT INTO balances (account_id, amount_minor, currency, balance_type, as_of, fetched_at)
                        VALUES (?,?,?,?,?,?)""",
                     (account_id, int((value * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)), "EUR",
                      BALANCE_TYPE, day.isoformat(), now))
        day += timedelta(days=1)
        days += 1
    return days


def depot_accounts(conn: sqlite3.Connection) -> list[int]:
    return [r[0] for r in conn.execute("SELECT DISTINCT account_id FROM depot_trades")]


# --- quotes ---------------------------------------------------------------------------

def parse_chart(data: bytes) -> tuple[Optional[str], list[tuple[str, Decimal]]]:
    """Yahoo chart JSON -> (currency, [(date, close)])."""
    result = (json.loads(data).get("chart") or {}).get("result") or []
    if not result:
        return None, []
    res = result[0]
    currency = (res.get("meta") or {}).get("currency")
    stamps = res.get("timestamp") or []
    closes = (((res.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
    out = []
    for ts, close in zip(stamps, closes):
        if close is None:
            continue
        day = datetime.fromtimestamp(ts, timezone.utc).date().isoformat()
        out.append((day, Decimal(str(close)).quantize(Decimal("0.0001"))))
    return currency, out


def update_quotes(conn: sqlite3.Connection, symbols: dict[str, str], fetch: Callable[[str], bytes],
                  today: date) -> int:
    """Fetch daily closes for held ISINs that have a symbol, then revalue -> prices stored."""
    stored = 0
    for isin in {r[0] for r in conn.execute("SELECT DISTINCT isin FROM depot_trades")}:
        symbol = symbols.get(isin)
        if not symbol:
            continue
        last = conn.execute("SELECT MAX(date) FROM security_prices WHERE isin=? AND source='quote'",
                            (isin,)).fetchone()[0]
        first = conn.execute("SELECT MIN(booking_date) FROM depot_trades WHERE isin=?", (isin,)).fetchone()[0]
        start = date.fromisoformat(last or first) - timedelta(days=5)
        end = today + timedelta(days=1)
        url = QUOTE_URL.format(symbol=symbol, start=_epoch(start), end=_epoch(end))
        currency, closes = parse_chart(fetch(url))
        if currency != "EUR":
            continue
        for day, price in closes:
            conn.execute("""INSERT OR REPLACE INTO security_prices (isin, date, price, currency, source)
                            VALUES (?,?,?,?,'quote')""", (isin, day, str(price), "EUR"))
            stored += 1
    for account_id in depot_accounts(conn):
        revalue(conn, account_id, today)
    return stored


def _epoch(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())
