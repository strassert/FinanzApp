import io
import zipfile
from datetime import date

from finanzen.core import fx
from finanzen.core.recompute import recompute

from .helpers import one

CSV = """Date,USD,JPY,GBP,CYP,
2026-09-25,1.1700,170.10,0.8500,N/A,
2026-09-24,1.1650,169.00,0.8480,N/A,
2026-08-31,1.1000,160.00,0.8400,N/A,
"""


def zipped(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("eurofxref-hist.csv", text)
    return buf.getvalue()


DAILY = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time="2026-09-28"><Cube currency="USD" rate="1.1800"/><Cube currency="GBP" rate="0.8510"/></Cube></Cube>
</gesmes:Envelope>"""


def test_history_then_daily(conn):
    urls = []

    def fetch(url):
        urls.append(url)
        return zipped(CSV) if url == fx.HISTORY_URL else DAILY.encode()

    assert fx.update_rates(conn, fetch) == 9          # N/A skipped
    assert fx.update_rates(conn, fetch) == 2
    assert urls == [fx.HISTORY_URL, fx.DAILY_URL]


def test_rate_of_booking_date_or_last_published(conn):
    fx.store_rates(conn, fx.parse_history_csv(CSV))
    rates = fx.Rates(conn)
    assert rates.to_eur(-1170, "USD", date(2026, 9, 25)) == -1000
    assert rates.to_eur(-1170, "USD", date(2026, 9, 27)) == -1000     # Sunday -> Friday's rate
    assert rates.to_eur(-1000, "JPY", date(2026, 9, 25)) == -588       # JPY has no minor unit
    assert rates.to_eur(-1000, "USD", date(2026, 9, 10)) is None       # gap > 7 days
    assert rates.to_eur(-1000, "CHF", date(2026, 9, 25)) is None       # unknown currency
    assert rates.to_eur(-1000, "EUR", date(1990, 1, 1)) == -1000


def test_foreign_transactions_without_rate_are_not_converted(conn, linked):
    usd = one(conn, ref="PP-USD-1")
    assert usd["amount_eur_minor"] is None
    fx.store_rates(conn, [(usd["booking_date"], "USD", "1.1000")])
    recompute(conn)
    assert one(conn, ref="PP-USD-1")["amount_eur_minor"] == -1181
