"""ECB euro reference rates.

Rates are stored as "units of currency per 1 EUR". A transaction is converted
with the rate of its booking date, or the last published rate up to 7 days
before (weekends, holidays). Without a rate the amount is left out of sums
and counted as "nicht umgerechnet".
"""

from __future__ import annotations

import csv
import io
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from bisect import bisect_right
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

from ..money import exponent

HISTORY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
MAX_AGE_DAYS = 7


def parse_history_csv(text: str) -> Iterable[tuple[str, str, str]]:
    """Parse eurofxref-hist.csv: Date,USD,JPY,... -> (date, currency, rate)."""
    reader = csv.reader(io.StringIO(text))
    header = [h.strip() for h in next(reader)]
    for row in reader:
        if not row or not row[0].strip():
            continue
        day = row[0].strip()
        for currency, value in zip(header[1:], row[1:]):
            value = value.strip()
            if currency and value and value != "N/A":
                yield day, currency, value


def parse_history_zip(data: bytes) -> Iterable[tuple[str, str, str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".csv"))
        yield from parse_history_csv(zf.read(name).decode("utf-8"))


def parse_daily_xml(text: str) -> Iterable[tuple[str, str, str]]:
    root = ET.fromstring(text)
    for cube in root.iter():
        if cube.tag.endswith("Cube") and cube.get("time"):
            day = cube.get("time")
            for rate in cube:
                yield day, rate.get("currency"), rate.get("rate")


def store_rates(conn: sqlite3.Connection, rates: Iterable[tuple[str, str, str]]) -> int:
    n = 0
    for day, currency, rate in rates:
        conn.execute("INSERT OR REPLACE INTO fx_rates (date, currency, rate) VALUES (?,?,?)",
                     (day, currency, rate))
        n += 1
    return n


def update_rates(conn: sqlite3.Connection, fetch) -> int:
    """Fetch rates via `fetch(url) -> bytes`: the full history once, then daily."""
    has_any = conn.execute("SELECT 1 FROM fx_rates LIMIT 1").fetchone()
    if has_any:
        return store_rates(conn, parse_daily_xml(fetch(DAILY_URL).decode("utf-8")))
    return store_rates(conn, parse_history_zip(fetch(HISTORY_URL)))


class Rates:
    """In-memory lookup, loaded once per recomputation."""

    def __init__(self, conn: sqlite3.Connection):
        self._dates: dict[str, list[str]] = {}
        self._rates: dict[str, list[Decimal]] = {}
        for row in conn.execute("SELECT date, currency, rate FROM fx_rates ORDER BY currency, date"):
            self._dates.setdefault(row["currency"], []).append(row["date"])
            self._rates.setdefault(row["currency"], []).append(Decimal(row["rate"]))

    def rate(self, currency: str, day: date) -> Optional[Decimal]:
        if currency == "EUR":
            return Decimal(1)
        dates = self._dates.get(currency)
        if not dates:
            return None
        i = bisect_right(dates, day.isoformat()) - 1
        if i < 0:
            return None
        if date.fromisoformat(dates[i]) < day - timedelta(days=MAX_AGE_DAYS):
            return None
        return self._rates[currency][i]

    def to_eur(self, amount_minor: int, currency: str, day: date) -> Optional[int]:
        if currency == "EUR":
            return amount_minor
        rate = self.rate(currency, day)
        if rate is None or rate == 0:
            return None
        major = Decimal(amount_minor).scaleb(-exponent(currency)) / rate
        return int((major * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
