from datetime import date, timedelta

from finanzen.core import recurring
from finanzen.core.forecast import forecast, project
from finanzen.core.recompute import recompute
from finanzen.core.recurring import Booking, add_months, detect

from .conftest import TODAY

_ids = iter(range(1, 10_000))


def bk(day, amount, name, role=None, source="api"):
    role = role or ("income" if amount > 0 else "expense")
    return Booking(next(_ids), 1, day, amount, role, name, "", None, source)


def series(first, n, amount, name, role=None):
    return [bk(add_months(first, i), amount, name, role) for i in range(n)]


ROLES = ("expense", "income", "transfer")
RENT = series(date(2026, 4, 1), 6, -95000, "Hausverwaltung")          # last 1 Sep, next 1 Oct
SAVINGS = series(date(2026, 4, 3), 6, -20000, "Max Mustermann", "transfer")


def run(pending=(), in_balance=False, booked=(), until=date(2026, 10, 28), extra=()):
    items = detect(RENT + SAVINGS + list(extra), TODAY, ROLES)
    return project(100000, list(pending), in_balance, items, TODAY, until, list(booked))


def test_balance_minus_expected_bookings():
    p = run()
    assert [(e.date, e.amount) for e in p["expected"]] == [(date(2026, 10, 1), -95000), (date(2026, 10, 3), -20000)]
    assert p["forecast"] == 100000 - 95000 - 20000
    assert (p["lowest"], p["lowest_date"]) == (-15000, date(2026, 10, 3))


def test_until_limits_and_repeats():
    assert run(until=date(2026, 9, 30))["expected"] == []
    p = run(until=date(2026, 11, 30))
    assert len(p["expected"]) == 4                       # two months of rent and savings


def test_pending_counts_unless_in_balance_but_wallet_always():
    shop = bk(TODAY, -3000, "BILLA")
    apple = bk(TODAY, -1200, "Cafe", source="wallet")
    assert run(pending=[shop, apple])["pending"] == -4200
    assert run(pending=[shop, apple], in_balance=True)["pending"] == -1200


def test_pending_rent_replaces_the_expected_one():
    pending_rent = bk(date(2026, 9, 30), -95000, "Hausverwaltung")
    p = run(pending=[pending_rent])
    assert [e.name for e in p["expected"]] == ["Max Mustermann"]
    assert p["forecast"] == 100000 - 95000 - 20000        # counted once, as pending


def test_booked_payment_with_other_amount_covers_overdue_one():
    bill = series(date(2026, 3, 11), 6, -2398, "BAWAG")                 # last 11 Aug, next 11 Sep
    assert [e.overdue for e in run(extra=bill)["expected"] if e.name == "BAWAG"] == [True, False]
    holiday_bill = [bk(date(2026, 9, 11), -89000, "BAWAG")]
    p = run(extra=bill, booked=holiday_bill)
    assert [e.date for e in p["expected"] if e.name == "BAWAG"] == [date(2026, 10, 11)]


# --- with the fake bank -------------------------------------------------------------

def giro(data):
    return next(a for a in data["accounts"] if a["kind"] == "giro")


def test_scenario_forecast(conn, linked):
    data = forecast(conn, TODAY, TODAY + timedelta(days=30))
    g = giro(data)
    names = [e["name"] for e in g["expected"]]
    assert "Hausverwaltung Sonnenhof" in names and "Salzburg AG" in names
    assert any(e["role"] == "transfer" for e in g["expected"])          # savings plan to flatex
    assert g["forecast"] == g["balance"] + g["pending"] + sum(e["amount"] for e in g["expected"])
    assert data["forecast"] == sum(a["forecast"] for a in data["accounts"])
    assert all(a["kind"] not in ("depot",) for a in data["accounts"])


def test_rejected_payee_leaves_the_forecast(conn, linked):
    before = giro(forecast(conn, TODAY, TODAY + timedelta(days=30)))
    rent = next(e for e in before["expected"] if e["name"] == "Hausverwaltung Sonnenhof")
    recurring.decide(conn, rent["key"], "rejected")
    recompute(conn)
    after = giro(forecast(conn, TODAY, TODAY + timedelta(days=30)))
    assert after["forecast"] == before["forecast"] + 95000


# --- credit card settlement -----------------------------------------------------------

def card(data):
    return next(a for a in data["accounts"] if a["kind"] == "card")


def test_next_settlement():
    from finanzen.core.forecast import next_settlement
    assert next_settlement(date(2026, 9, 11), date(2026, 9, 28)) == date(2026, 10, 11)
    assert next_settlement(date(2026, 8, 11), date(2026, 9, 14)) == date(2026, 9, 11)   # 3 days late
    assert next_settlement(date(2026, 6, 11), date(2026, 9, 28)) == date(2026, 10, 11)


def test_card_settlement_moves_open_amount_to_giro(conn, linked):
    data = forecast(conn, TODAY, TODAY + timedelta(days=30))
    c, g = card(data), giro(data)
    owed = -(c["balance"] + c["pending"])
    assert owed > 0
    [on_giro] = [e for e in g["expected"] if e["key"].startswith("card:")]
    [on_card] = [e for e in c["expected"] if e["key"].startswith("card:")]
    assert on_giro["amount"] == -owed and on_card["amount"] == owed
    assert on_giro["name"] == f"Abrechnung {c['name']}" and on_giro["date"] == on_card["date"]
    # the settlement is not also expected as a recurring transfer
    assert not any(e["role"] == "transfer" and not e["key"].startswith("card:") and "PAYLIFE" in e["name"].upper()
               for e in g["expected"])
    assert not any("ZAHLUNG ERHALTEN" in e["name"] for e in c["expected"])


def test_imported_card_without_balance_sums_its_bookings(conn, linked):
    before = card(forecast(conn, TODAY, TODAY + timedelta(days=30)))
    owed = -(before["balance"] + before["pending"])
    card_id = before["id"]
    conn.execute("UPDATE accounts SET source='import' WHERE id=?", (card_id,))
    conn.execute("DELETE FROM balances WHERE account_id=?", (card_id,))
    g = giro(forecast(conn, TODAY, TODAY + timedelta(days=30)))
    [on_giro] = [e for e in g["expected"] if e["key"] == f"card:{card_id}"]
    assert on_giro["amount"] == -owed
