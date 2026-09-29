from datetime import date, timedelta

from finanzen.core import queries, reports
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
    assert ov["period"]["label"] == "September 2026"          # calendar month
    assert (ov["period"]["start"], ov["period"]["end"]) == ("2026-09-01", "2026-09-30")
    assert len(ov["trend"]) == 12 and ov["trend"][-1]["key"] == "2026-09"
    assert ov["previous"]["spent_same_day"] <= ov["previous"]["spent"]
    assert ov["budget"]["days_left"] == 3                   # 28, 29, 30 Sep


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


def test_budget_subtracts_fixed_costs_still_expected(conn, linked):
    from finanzen.core import recurring
    from finanzen.core.periods import Period
    period = Period(2026, 10, TODAY, date(2026, 10, 28))
    s = reports.sums(conn, period.start, period.end)
    b = reports.budget(conn, period, TODAY, s)
    expected = recurring.upcoming(conn, TODAY, period.end)
    assert {"Hausverwaltung Sonnenhof", "Salzburg AG"} <= {e.name for e in expected}
    assert all(e.role in ("expense", "income") for e in expected)          # no savings transfers
    assert b["fixed_expected"] == sum(e.amount for e in expected if e.role == "expense") < 0
    assert b["remaining"] == s.income - s.spent + b["fixed_expected"] + b["income_expected"]
    assert b["per_day"] == b["remaining"] // b["days_left"]
    rent = next(e for e in expected if e.name == "Hausverwaltung Sonnenhof")
    recurring.decide(conn, rent.key, "rejected")
    assert reports.budget(conn, period, TODAY, s)["remaining"] == b["remaining"] + 95000


def test_budget_of_a_past_period_expects_nothing(conn, linked):
    cal = reports.calendar(conn)
    past = cal.previous(cal.period_for(TODAY))
    s = reports.sums(conn, past.start, past.end)
    b = reports.budget(conn, past, TODAY, s)
    assert b["fixed_expected"] == 0 and b["remaining"] == s.income - s.spent and b["per_day"] is None


def test_budget_follows_card_selection(conn, linked):
    from finanzen.core.periods import Period
    period = Period(2026, 10, TODAY, date(2026, 10, 28))
    card = acc_id(conn, "PayLife")
    s = reports.sums(conn, period.start, period.end, [card])
    assert reports.budget(conn, period, TODAY, s, [card])["fixed_expected"] == 0   # rent is on the giro


def test_category_average_over_complete_past_periods(conn, linked):
    cal = reports.calendar(conn)
    period = cal.period_for(TODAY)
    periods, avg = reports.category_averages(conn, cal, period)
    first = conn.execute("SELECT MIN(booking_date) FROM transactions").fetchone()[0]
    assert 0 < len(periods) <= 12 and all(p.start.isoformat() >= first for p in periods)
    assert period not in periods
    rent = next(c for c in reports.by_category(conn, periods[0].start, periods[0].end) if c["name"] == "Wohnen")
    wohnen = sum(c["amount"] for p in periods for c in reports.by_category(conn, p.start, p.end)
                 if c["id"] == rent["id"])
    assert avg[rent["id"]] == round(wohnen / len(periods)) >= 95000
    total = sum(sum(c["amount"] for c in reports.by_category(conn, p.start, p.end)) for p in periods)
    assert abs(sum(avg.values()) - total / len(periods)) <= len(avg)  # rounding per category
    ov = reports.overview(conn, period, TODAY)
    assert ov["average_periods"] == len(periods)
    assert next(c for c in ov["categories"] if c["id"] == rent["id"])["average"] == avg[rent["id"]]


def test_category_average_needs_history(conn):
    cal = reports.calendar(conn)
    assert reports.category_averages(conn, cal, cal.period_for(TODAY)) == ([], {})


def test_late_salary_counts_for_next_calendar_month(conn, linked):
    days = {r["booking_date"]: r["budget_date"] for r in conn.execute(
        """SELECT t.booking_date, d.budget_date FROM transactions t JOIN tx_derived d ON d.tx_id=t.id
           WHERE t.description LIKE 'GEHALT%'""")}
    assert days["2026-08-28"] == "2026-09-01" and days["2026-07-29"] == "2026-08-01"
    cal = reports.calendar(conn)

    def salary(start, end):
        return sum(c["amount"] for c in reports.by_category(conn, start, end, role="income") if c["name"] == "Gehalt")
    assert salary(date(2026, 8, 1), date(2026, 8, 31)) == 324000     # July's salary only
    sep = cal.period_for(TODAY)
    assert salary(sep.start, sep.end) == 324000                      # paid 28 Aug
    listed = queries.list_transactions(conn, start=sep.start, end=sep.end, query="GEHALT")["items"]
    assert [(t["date"], t["budget_date"]) for t in listed] == [("2026-08-28", "2026-09-01")]


def test_salary_to_salary_periods_stay_available(conn, linked):
    from finanzen.core.db import set_setting
    set_setting(conn, "salary_day", "29")
    recompute(conn)
    period = reports.calendar(conn).period_for(TODAY)
    assert (period.label, period.start) == ("September 2026", date(2026, 8, 28))   # salary on 28 Aug
    row = conn.execute("""SELECT t.booking_date, d.budget_date FROM transactions t JOIN tx_derived d
                          ON d.tx_id=t.id WHERE t.description LIKE 'GEHALT%' ORDER BY t.booking_date DESC""").fetchone()
    assert row[0] == row[1]


def test_budget_does_not_count_next_months_salary(conn, linked):
    from finanzen.core import recurring
    from finanzen.core.periods import Period
    sep = Period(2026, 9, date(2026, 9, 1), date(2026, 9, 30))
    expected = recurring.upcoming(conn, TODAY, sep.end)
    assert any(e.role == "income" and e.date == date(2026, 9, 28) for e in expected)   # salary due today
    b = reports.budget(conn, sep, TODAY, reports.sums(conn, sep.start, sep.end))
    assert b["income_expected"] == 0                          # it is October's money
