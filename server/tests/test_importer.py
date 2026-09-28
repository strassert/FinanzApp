import io
from datetime import date, datetime
from decimal import Decimal

import pytest

from finanzen.core import importer
from finanzen.core.importer import ImportError_, Mapping, parse_amount, parse_date, preview, run_import
from finanzen.core.recompute import recompute
from finanzen.core.store import create_manual_account


@pytest.mark.parametrize("text,expected", [
    ("1.234,56", "1234.56"), ("1,234.56", "1234.56"), ("12,50-", "-12.50"), ("(3.20)", "-3.20"),
    ("−12,50", "-12.50"), ("€ 12,50", "12.50"), ("12.50 EUR", "12.50"), ("+5", "5"),
    ("-1.234", "-1234"), ("1.234.567,00", "1234567.00"), ("1,234,567", "1234567"), ("0,99", "0.99"),
    ("12.5", "12.5"), ("", None), ("Umsatztext", None), ("12a", None),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == (Decimal(expected) if expected else None)


def test_parse_date():
    assert parse_date("28.09.2026") == date(2026, 9, 28)
    assert parse_date("28.09.26") == date(2026, 9, 28)
    assert parse_date("2026-09-28 14:03:00") == date(2026, 9, 28)
    assert parse_date("28/09/2026") == date(2026, 9, 28)
    assert parse_date("Datum") is None


def test_file_type_by_first_bytes():
    assert importer.detect_kind(b"%PDF-1.7 ...") == "pdf"
    assert importer.detect_kind(b"PK\x03\x04rest") == "xlsx"
    assert importer.detect_kind(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1rest") == "xls"
    assert importer.detect_kind(b"Datum;Betrag") == "csv"


def test_pdf_is_rejected_clearly():
    with pytest.raises(ImportError_, match="CSV oder Excel"):
        importer.read_rows(b"%PDF-1.4 whatever")


PAYLIFE_CSV = """Kreditkartenabrechnung PayLife
Karte: XXXX XXXX XXXX 1234
Zeitraum: 01.08.2026 - 31.08.2026

Buchungsdatum;Umsatztext;Betrag;Währung
03.08.2026;BILLA DANKT 4711;-45,30;EUR
05.08.2026;CAFE TOMASELLI;-4,20;EUR
05.08.2026;CAFE TOMASELLI;-4,20;EUR
10.08.2026;ZAHLUNG ERHALTEN;312,40;EUR
""".encode("cp1252")


def test_csv_with_preamble_cp1252_and_umsatztext(conn):
    acc = create_manual_account(conn, "PayLife", "card", source="import")
    p = preview(conn, PAYLIFE_CSV, acc)
    m = p["mapping"]
    assert p["columns"][m["date"]] == "Buchungsdatum"
    assert p["columns"][m["amount"]] == "Betrag"          # not "Umsatztext"
    assert p["columns"][m["text"][0]] == "Umsatztext"
    assert p["count"] == 4 and p["parsed"][0]["amount"] == -4530


def test_import_twice_adds_only_new_and_keeps_two_coffees(conn):
    acc = create_manual_account(conn, "PayLife", "card", source="import")
    m = preview(conn, PAYLIFE_CSV, acc)["mapping"]
    first = run_import(conn, PAYLIFE_CSV, acc, m)
    assert first["new"] == 4
    more = PAYLIFE_CSV + "12.08.2026;OMV TANKSTELLE;-60,00;EUR\n".encode("cp1252")
    second = run_import(conn, more, acc, m)
    assert (second["new"], second["known"]) == (1, 4)
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE description='CAFE TOMASELLI'").fetchone()[0] == 2
    # the mapping is remembered for the account
    assert preview(conn, more, acc)["remembered"] is True


def test_debit_credit_columns_and_inverted_sign(conn):
    data = ("Datum;Text;Soll;Haben\n01.09.2026;Miete;950,00;\n02.09.2026;Gehalt;;3.240,00\n").encode()
    acc = create_manual_account(conn, "Alt", "giro", source="import")
    p = preview(conn, data, acc)
    assert [t["amount"] for t in p["parsed"]] == [-95000, 324000]
    m = dict(p["mapping"], invert=True)
    run_import(conn, data, acc, m)
    assert sorted(r[0] for r in conn.execute("SELECT amount_minor FROM transactions")) == [-324000, 95000]


def test_utf8_bom_comma_separated(conn):
    data = "﻿Date,Description,Amount,Balance\n2026-09-01,Coffee,-3.50,96.50\n2026-09-02,Refund,10.00,106.50\n".encode("utf-8")
    acc = create_manual_account(conn, "Card", "card", source="import")
    p = preview(conn, data, acc)
    assert [t["amount"] for t in p["parsed"]] == [-350, 1000]
    run_import(conn, data, acc, p["mapping"])
    bal = conn.execute("SELECT amount_minor, as_of FROM balances WHERE account_id=?", (acc,)).fetchone()
    assert tuple(bal) == (10650, "2026-09-02")


def test_paypal_template_skips_pending(conn):
    data = ('"Datum","Uhrzeit","Zeitzone","Name","Typ","Status","Währung","Brutto","Gebühr","Netto","Guthaben"\n'
            '"12.09.2026","10:00:00","CEST","Zalando SE","PayPal Express-Zahlung","Abgeschlossen","EUR","-49,95","0,00","-49,95","0,00"\n'
            '"13.09.2026","10:00:00","CEST","Steam","Zahlung","Ausstehend","EUR","-5,00","0,00","-5,00","0,00"\n').encode()
    acc = create_manual_account(conn, "PayPal", "paypal", source="import")
    p = preview(conn, data, acc)
    assert p["template"] == "PayPal (Deutsch)"
    assert p["count"] == 1 and p["skipped"] == 1
    assert p["parsed"][0]["counterparty"] == "Zalando SE"


def test_xlsx_first_sheet_numbers_and_dates(conn):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Umsätze Kreditkarte"])
    ws.append([])
    ws.append(["Buchungsdatum", "Beschreibung", "Betrag"])
    ws.append([datetime(2026, 9, 3), "SPAR FIL. 5020", -23.4])
    ws.append([datetime(2026, 9, 4), "OEBB", -12])
    buf = io.BytesIO()
    wb.save(buf)
    acc = create_manual_account(conn, "Card", "card", source="import")
    p = preview(conn, buf.getvalue(), acc)
    assert [(t["date"], t["amount"]) for t in p["parsed"]] == [("2026-09-03", -2340), ("2026-09-04", -1200)]


def test_import_vs_api_duplicate_is_suggested(conn, linked):
    giro = conn.execute("SELECT id FROM accounts WHERE institution='Volksbank Salzburg'").fetchone()[0]
    rent = conn.execute("SELECT booking_date FROM transactions WHERE account_id=? AND description LIKE 'MIETE%' "
                        "ORDER BY booking_date DESC", (giro,)).fetchone()[0]
    d = date.fromisoformat(rent)
    data = f"Datum;Text;Betrag\n{d.strftime('%d.%m.%Y')};Miete Top 4;-950,00\n".encode()
    run_import(conn, data, giro, preview(conn, data, giro)["mapping"])
    recompute(conn)
    kinds = [r[0] for r in conn.execute("SELECT kind FROM links WHERE status='suggested'")]
    assert "duplicate" in kinds
