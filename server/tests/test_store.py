from datetime import date

from finanzen.core.store import NewTx, assign_ext_ids, create_manual_account, upsert_transactions


def coffee(day=date(2026, 9, 1), amount=-350, text="CAFE TOMASELLI"):
    return NewTx(booking_date=day, amount_minor=amount, currency="EUR", description=text)


def test_two_identical_coffees_stay_two():
    ids = [i for i, _ in assign_ext_ids([coffee(), coffee()])]
    assert len(set(ids)) == 2


def test_fingerprint_ignores_case_and_spacing():
    a = assign_ext_ids([coffee(text="Cafe  Tomaselli")])[0][0]
    b = assign_ext_ids([coffee(text="CAFE TOMASELLI")])[0][0]
    assert a == b


def test_same_bank_reference_is_one_record():
    tx = coffee()
    tx.ext_ref = "REF-1"
    assert len(assign_ext_ids([tx, tx])) == 1


def test_reimport_of_overlapping_file_adds_only_new(conn):
    acc = create_manual_account(conn, "Karte", "card", source="import")
    first = [coffee(date(2026, 9, 1)), coffee(date(2026, 9, 2))]
    assert len(upsert_transactions(conn, acc, "import", first).new_ids) == 2
    second = [coffee(date(2026, 9, 2)), coffee(date(2026, 9, 2)), coffee(date(2026, 9, 3))]
    result = upsert_transactions(conn, acc, "import", second)
    assert len(result.new_ids) == 2           # the second coffee on 2 Sep and 3 Sep
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 4
