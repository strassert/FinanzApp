from datetime import date, timedelta

from finanzen.core import reports
from finanzen.core.fx import store_rates
from finanzen.core.recompute import recompute

from .conftest import TODAY


def acc_id(conn, institution, currency="EUR"):
    return conn.execute("SELECT id FROM accounts WHERE institution=? AND currency=?",
                        (institution, currency)).fetchone()[0]


def test_past_balance_is_latest_minus_bookings_since(conn, linked):
    first = date.fromisoformat(conn.execute("SELECT MIN(booking_date) FROM transactions").fetchone()[0])
    before = first - timedelta(days=1)
    bal = reports.account_balances(conn, [before, TODAY])
    assert bal[acc_id(conn, "Volksbank Salzburg")][before] == 215000   # opening balance in the scenario
    assert bal[acc_id(conn, "flatex")][before] == 30000
    assert bal[acc_id(conn, "PayLife")][before] == 0


def test_bank_funded_paypal_purchase_does_not_move_paypal_balance(conn, linked):
    first = date.fromisoformat(conn.execute("SELECT MIN(booking_date) FROM transactions").fetchone()[0])
    before = first - timedelta(days=1)
    bal = reports.account_balances(conn, [before])
    assert bal[acc_id(conn, "PayPal")][before] == 0


def test_net_worth_counts_unconverted_accounts(conn, linked):
    nw = reports.net_worth(conn, [TODAY])[0]
    assert nw["not_converted"] == 1          # PayPal USD without rates
    store_rates(conn, [(TODAY.isoformat(), "USD", "1.2")])
    assert reports.net_worth(conn, [TODAY])[0]["not_converted"] == 0


def test_net_worth_includes_manual_depot_value(conn, linked):
    from finanzen.core.store import create_manual_account, store_balance
    base = reports.net_worth(conn, [TODAY])[0]["value"]
    depot = create_manual_account(conn, "flatex Depot", "depot")
    store_balance(conn, depot, 1234500, "EUR", "MANUAL", TODAY - timedelta(days=10))
    assert reports.net_worth(conn, [TODAY])[0]["value"] == base + 1234500
    assert reports.net_worth(conn, [TODAY - timedelta(days=11)])[0]["value"] != base + 1234500


def test_overview_consistency(conn, linked):
    cal = reports.calendar(conn)
    period = cal.period_for(TODAY)
    ov = reports.overview(conn, period, TODAY)
    assert ov["spent"] > 0 and ov["income"] > 0
    assert sum(c["amount"] for c in ov["categories"]) == ov["spent"]
    assert sum(c["amount"] for c in ov["cards"]) == ov["spent"]
    assert ov["period"]["label"] == "September 2026"          # salary 28 Aug -> September
    assert ov["period"]["start"] == "2026-08-28"
    assert len(ov["trend"]) == 12 and ov["trend"][-1]["key"] == "2026-09"
    assert ov["previous"]["spent_same_day"] <= ov["previous"]["spent"]
    assert ov["budget"]["days_left"] == 1                   # 28 Sep, salary expected 29 Sep


def test_card_filter_limits_sums(conn, linked):
    period = reports.calendar(conn).period_for(TODAY)
    card = acc_id(conn, "PayLife")
    ov = reports.overview(conn, period, TODAY, [card])
    all_ = reports.overview(conn, period, TODAY)
    card_row = next(c for c in all_["cards"] if c["id"] == card)
    assert ov["spent"] == card_row["amount"]


def test_sankey_flows_balance(conn, linked):
    period = reports.calendar(conn).previous(reports.calendar(conn).period_for(TODAY))
    s = reports.sankey(conn, period.start, period.end)
    into_pot = sum(l["value"] for l in s["links"] if l["target"] == "pot")
    out_of_pot = sum(l["value"] for l in s["links"] if l["source"] == "pot")
    assert into_pot == out_of_pot
    for n in s["nodes"]:
        if n["kind"] == "account":
            inflow = sum(l["value"] for l in s["links"] if l["target"] == n["id"])
            outflow = sum(l["value"] for l in s["links"] if l["source"] == n["id"])
            assert inflow == outflow
    assert not any("Umbuchung" == n["label"] for n in s["nodes"])


def test_mask_iban():
    assert reports.mask_iban("AT45 4501 0000 0012 3456") == "AT45 •••• 3456"
    assert reports.mask_iban(None) is None
