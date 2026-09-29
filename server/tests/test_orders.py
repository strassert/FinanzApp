"""Amazon order history: parsing, matching shipments to card charges, splitting."""

import io
import zipfile
from datetime import date

import pytest

from finanzen.core import orders, reports
from finanzen.core.categories import add_rule, ids_by_name
from finanzen.core.db import utcnow
from finanzen.core.importer import ImportError_
from finanzen.core.recompute import recompute
from finanzen.core.store import NewTx, create_manual_account, upsert_transactions

HEADER = ('"Website","Order ID","Order Date","Currency","Unit Price","Total Owed","ASIN","Quantity",'
          '"Payment Instrument Type","Order Status","Ship Date","Product Name"')


def row(order, order_date, total, asin, name, ship="Not Available", status="Closed", qty=1):
    return (f'"Amazon.de","{order}","{order_date}","EUR","{total}","{total}","{asin}","{qty}",'
            f'"Visa - 1234","{status}","{ship}","{name}"')


CSV = "\n".join([
    HEADER,
    # order A: two items, shipped on two days -> two card charges
    row("302-1111111-1111111", "2026-09-01T18:02:11Z", "29.99", "B01", "Druckerpatronen XL 4er-Pack",
        ship="2026-09-02T06:00:00Z"),
    row("302-1111111-1111111", "2026-09-01T18:02:11Z", "54.98", "B02", "Laufschuhe Herren Gr. 44",
        ship="2026-09-04T06:00:00Z"),
    # order B: one shipment with two items -> one charge, split in two
    row("302-2222222-2222222", "2026-09-10T09:00:00Z", "12.99", "B03", "USB-C Kabel 2m",
        ship="2026-09-10T20:00:00Z"),
    row("302-2222222-2222222", "2026-09-10T09:00:00Z", "8.50", "B04", "Bio Kaffee 500g",
        ship="2026-09-10T20:00:00Z"),
    # cancelled: ignored
    row("302-3333333-3333333", "2026-09-12T09:00:00Z", "99.00", "B05", "Storniert", status="Cancelled"),
    # late evening UTC order is the next day in Vienna
    row("302-4444444-4444444", "2026-09-14T22:30:00Z", "15.00", "B06", "Buch", ship="2026-09-15T08:00:00Z"),
]) + "\n"


def charge(conn, acc, day, amount, text="AMAZON.DE*AB12CD34E AMAZON.DE LU", ref=None):
    return upsert_transactions(conn, acc, "api", [NewTx(
        booking_date=date.fromisoformat(day), amount_minor=amount, currency="EUR",
        description=text, ext_ref=ref or f"{day}{amount}{text[:5]}")]).new_ids[0]


@pytest.fixture
def giro(conn):
    return create_manual_account(conn, "Volksbank", "giro")


def split_rows(conn, tx_id):
    return conn.execute("""SELECT i.name, s.amount_eur_minor, c.name AS cat, s.category_source
                           FROM tx_splits s JOIN order_items i ON i.id=s.item_id
                           JOIN categories c ON c.id=s.category_id WHERE s.tx_id=? ORDER BY i.id""",
                        (tx_id,)).fetchall()


# --- parsing -------------------------------------------------------------------------

def test_parse_csv_skips_cancelled_and_uses_local_dates():
    items = orders.parse_amazon(CSV.encode())
    assert len(items) == 5
    assert {i.order_id for i in items} == {"302-1111111-1111111", "302-2222222-2222222", "302-4444444-4444444"}
    book = next(i for i in items if i.name == "Buch")
    assert book.order_date == date(2026, 9, 15)             # 22:30 UTC = 00:30 in Vienna
    shoes = next(i for i in items if i.name.startswith("Laufschuhe"))
    assert shoes.amount_minor == 5498 and shoes.shipment_key == "302-1111111-1111111|2026-09-04"


def test_parse_zip_and_reject_other_files():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Retail.OrderHistory.1/Retail.OrderHistory.1.csv", CSV)
        zf.writestr("Retail.OrderHistory.1/README.txt", "x")
    assert len(orders.parse_amazon(buf.getvalue())) == 5
    with pytest.raises(ImportError_):
        orders.parse_amazon(b"Datum;Betrag\n01.01.2026;5\n")


def test_reimport_adds_nothing(conn):
    first = orders.import_items(conn, orders.parse_amazon(CSV.encode()))
    again = orders.import_items(conn, orders.parse_amazon(CSV.encode()))
    assert (first["new"], again["new"]) == (5, 0)


def test_allocate_sums_exactly():
    assert orders.allocate(-1000, [1, 1, 1]) == [-334, -333, -333]
    parts = orders.allocate(-4999, [2999, 2500])
    assert sum(parts) == -4999
    assert orders.allocate(-100, [0, 0]) == [-50, -50]


# --- matching and splitting --------------------------------------------------------------

def test_shipments_match_card_charges_and_split(conn, giro):
    a1 = charge(conn, giro, "2026-09-03", -2999)
    a2 = charge(conn, giro, "2026-09-05", -5498)
    b = charge(conn, giro, "2026-09-11", -2149)
    orders.import_items(conn, orders.parse_amazon(CSV.encode()))
    recompute(conn)
    statuses = {r["tx_id"]: r["status"] for r in conn.execute("SELECT * FROM order_matches")}
    assert statuses == {a1: "auto", a2: "auto", b: "auto"}
    lines = split_rows(conn, b)
    assert [(l["name"], l["amount_eur_minor"]) for l in lines] == [("USB-C Kabel 2m", -1299), ("Bio Kaffee 500g", -850)]
    assert sum(l["amount_eur_minor"] for l in lines) == -2149           # always the bank amount


def test_item_categories_rules_and_user_choice(conn, giro):
    b = charge(conn, giro, "2026-09-11", -2149)
    orders.import_items(conn, orders.parse_amazon(CSV.encode()))
    recompute(conn)
    assert {l["cat"] for l in split_rows(conn, b)} == {"Shopping"}       # default for orders
    ids = ids_by_name(conn)
    add_rule(conn, "KAFFEE", ids["Lebensmittel"])
    recompute(conn)
    cats = {l["name"]: (l["cat"], l["category_source"]) for l in split_rows(conn, b)}
    assert cats["Bio Kaffee 500g"] == ("Lebensmittel", "rule")
    cable = conn.execute("SELECT id FROM order_items WHERE name LIKE 'USB-C%'").fetchone()[0]
    conn.execute("UPDATE order_items SET user_category_id=? WHERE id=?", (ids["Freizeit"], cable))
    recompute(conn)
    cats = {l["name"]: (l["cat"], l["category_source"]) for l in split_rows(conn, b)}
    assert cats["USB-C Kabel 2m"] == ("Freizeit", "user")


def test_reports_use_item_categories_but_totals_stay(conn, giro):
    b = charge(conn, giro, "2026-09-11", -2149)
    recompute(conn)
    start, end = date(2026, 9, 1), date(2026, 9, 30)
    before = reports.sums(conn, start, end).spent
    orders.import_items(conn, orders.parse_amazon(CSV.encode()))
    add_rule(conn, "KAFFEE", ids_by_name(conn)["Lebensmittel"])
    recompute(conn)
    assert reports.sums(conn, start, end).spent == before == 2149
    cats = {c["name"]: c["amount"] for c in reports.by_category(conn, start, end)}
    assert cats == {"Shopping": 1299, "Lebensmittel": 850}


def test_only_amazon_debits_in_window_with_exact_amount(conn, giro):
    other = charge(conn, giro, "2026-09-11", -2149, text="BILLA DANKT 4711")
    late = charge(conn, giro, "2026-09-25", -2149)                     # 15 days after shipping
    wrong = charge(conn, giro, "2026-09-11", -2150)
    orders.import_items(conn, orders.parse_amazon(CSV.encode()))
    recompute(conn)
    matched = {r[0] for r in conn.execute("SELECT tx_id FROM order_matches")}
    assert not matched & {other, late, wrong}


def test_ambiguous_match_is_a_suggestion_until_decided(conn, giro):
    t1 = charge(conn, giro, "2026-09-11", -2149, ref="x1")
    t2 = charge(conn, giro, "2026-09-12", -2149, ref="x2")
    orders.import_items(conn, orders.parse_amazon(CSV.encode()))
    recompute(conn)
    m = conn.execute("SELECT * FROM order_matches WHERE shipment_key LIKE '302-2222222%'").fetchone()
    assert m["status"] == "suggested" and m["tx_id"] in (t1, t2)
    assert conn.execute("SELECT COUNT(*) FROM tx_splits").fetchone()[0] == 0   # not split until confirmed
    conn.execute("INSERT INTO order_decisions VALUES (?,?, 'confirmed', ?)", (m["shipment_key"], t2, utcnow()))
    recompute(conn)
    assert len(split_rows(conn, t2)) == 2 and split_rows(conn, t1) == []


def test_rejected_candidate_is_not_suggested_again(conn, giro):
    t1 = charge(conn, giro, "2026-09-11", -2149)
    orders.import_items(conn, orders.parse_amazon(CSV.encode()))
    recompute(conn)
    key = conn.execute("SELECT shipment_key FROM order_matches WHERE tx_id=?", (t1,)).fetchone()[0]
    conn.execute("INSERT INTO order_decisions VALUES (?,?, 'rejected', ?)", (key, t1, utcnow()))
    recompute(conn)
    assert conn.execute("SELECT COUNT(*) FROM order_matches WHERE tx_id=?", (t1,)).fetchone()[0] == 0


def test_transfers_are_never_split(conn, giro):
    t = charge(conn, giro, "2026-09-11", -2149)
    conn.execute("UPDATE transactions SET user_excluded=1 WHERE id=?", (t,))
    orders.import_items(conn, orders.parse_amazon(CSV.encode()))
    recompute(conn)
    assert conn.execute("SELECT COUNT(*) FROM order_matches").fetchone()[0] == 0


def test_orders_never_delete_transactions(conn, giro):
    charge(conn, giro, "2026-09-11", -2149)
    n = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    orders.import_items(conn, orders.parse_amazon(CSV.encode()))
    recompute(conn)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == n
