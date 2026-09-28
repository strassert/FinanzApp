import json
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from finanzen.core import depot, importer
from finanzen.core.db import connect
from finanzen.core.reports import net_worth
from finanzen.core.store import create_manual_account

TODAY = date(2026, 9, 28)
ISIN = "IE00TEST0001"   # invented

# Invented rows in the flatex "Depotumsätze" format (semicolons, German numbers,
# unnamed currency columns, Windows-1252).
HEADER = ("Buchungstag;Valuta;Bezeichnung;ISIN;Nominal (Stk.);;Betrag;;Kurs;;Devisenkurs;TA.-Nr.;"
          "Buchungsinformation")
ROWS = [
    "05.09.2026;07.09.2026;TEST WORLD ETF;IE00TEST0001;10;Stück;1.000,00;EUR;100,00;EUR;1,000;9001;"
    "Ausführung ORDER Kauf IE00TEST0001 1",
    "15.09.2026;17.09.2026;TEST WORLD ETF;IE00TEST0001;4,5;Stück;495,00;EUR;110,00;EUR;1,000;9002;"
    "Ausführung ORDER Kauf IE00TEST0001 2",
    "16.09.2026;16.09.2026;TEST WORLD ETF;IE00TEST0001;-10;Stück;-1.050,00;EUR;105,00;EUR;1,000;9003;"
    "Thesaurierung transparenter Fonds IE00TEST0001",
    "16.09.2026;16.09.2026;TEST WORLD ETF;IE00TEST0001;10;Stück;1.060,00;EUR;106,00;EUR;1,000;9004;"
    "Thesaurierung transparenter Fonds IE00TEST0001",
]


def export(*rows: str) -> bytes:
    return "\n".join([HEADER, *rows]).encode("cp1252")


@pytest.fixture
def conn():
    return connect(":memory:")


@pytest.fixture
def account(conn):
    return create_manual_account(conn, "Depot", "depot")


def value_on(conn, account_id, day):
    row = conn.execute("SELECT amount_minor FROM balances WHERE account_id=? AND balance_type='DEPOT' AND as_of=?",
                       (account_id, day.isoformat())).fetchone()
    return row[0] if row else None


def test_parse_skips_tax_pairs(conn):
    rows = importer.read_rows(export(*ROWS))
    assert depot.is_flatex_depot(rows)
    trades, skipped = depot.parse_flatex_depot(rows)
    assert skipped == 2
    assert [t.quantity for t in trades] == [Decimal("10"), Decimal("4.5")]
    assert trades[0].amount_minor == 100000 and trades[0].price == Decimal("100.00")


def test_import_holdings_and_value_from_trade_prices(conn, account):
    result = importer.run_import(conn, export(*ROWS), account, {}, today=TODAY)
    assert (result["new"], result["known"], result["skipped"]) == (2, 0, 2)
    assert result["holdings"] == [{"isin": ISIN, "name": "TEST WORLD ETF", "quantity": "14.5"}]
    assert value_on(conn, account, date(2026, 9, 4)) is None          # before the first trade
    assert value_on(conn, account, date(2026, 9, 10)) == 100000       # 10 x 100
    assert value_on(conn, account, TODAY) == 159500                   # 14.5 x 110 (last known price)


def test_reimport_adds_only_new_trades(conn, account):
    importer.run_import(conn, export(*ROWS[:1]), account, {}, today=TODAY)
    result = importer.run_import(conn, export(*ROWS), account, {}, today=TODAY)
    assert (result["new"], result["known"]) == (1, 1)
    assert depot.holdings(conn, account, TODAY) == {ISIN: Decimal("14.5")}


def test_depot_export_needs_a_depot_account(conn):
    giro = create_manual_account(conn, "Giro", "other")
    with pytest.raises(importer.ImportError_):
        importer.preview(conn, export(*ROWS), giro)


def test_preview_shows_holdings(conn, account):
    data = importer.preview(conn, export(*ROWS), account)
    assert data["kind"] == "depot" and data["count"] == 2
    assert data["holdings"][0]["quantity"] == "14.5"


def chart(currency, closes):
    stamps = [int(datetime(d.year, d.month, d.day, 7, tzinfo=timezone.utc).timestamp()) for d, _ in closes]
    return json.dumps({"chart": {"result": [{
        "meta": {"currency": currency}, "timestamp": stamps,
        "indicators": {"quote": [{"close": [c for _, c in closes]}]}}]}}).encode()


def test_quotes_update_the_value_and_net_worth(conn, account):
    importer.run_import(conn, export(*ROWS), account, {}, today=TODAY)
    urls = []

    def fetch(url):
        urls.append(url)
        return chart("EUR", [(date(2026, 9, 25), 120.0), (date(2026, 9, 26), None)])

    assert depot.update_quotes(conn, {ISIN: "TEST.DE"}, fetch, TODAY) == 1
    assert "TEST.DE" in urls[0]
    assert value_on(conn, account, TODAY) == 174000                   # 14.5 x 120
    assert net_worth(conn, [TODAY])[0]["value"] == 174000


def test_quotes_ignore_other_currencies_and_unmapped_isins(conn, account):
    importer.run_import(conn, export(*ROWS), account, {}, today=TODAY)
    assert depot.update_quotes(conn, {ISIN: "TEST.L"}, lambda url: chart("USD", [(TODAY, 1.0)]), TODAY) == 0
    assert depot.update_quotes(conn, {}, lambda url: pytest.fail("no fetch without symbol"), TODAY) == 0
    assert value_on(conn, account, TODAY) == 159500
