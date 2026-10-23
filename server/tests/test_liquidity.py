"""Home screen summary: available until the next salary, net worth by kind."""

from datetime import date

from finanzen.core import liquidity, reports
from finanzen.core.fx import store_rates

from .conftest import TODAY


def test_available_is_balance_plus_every_line(conn, linked):
    s = liquidity.summary(conn, TODAY)
    assert s["available"] == s["balance"] + sum(l["amount"] for l in s["lines"])
    assert s["outgoing"] + s["incoming"] == sum(l["amount"] for l in s["lines"])


def test_runs_until_the_day_before_the_salary(conn, linked):
    # last salary Fri 28 Aug -> expected one month later, 28 Sep (= today in the scenario)
    s = liquidity.summary(conn, TODAY)
    assert s["salary"]["date"] == "2026-09-28" and s["salary"]["amount"] == 324000
    assert s["until"] == "2026-09-28"                   # never before today
    s = liquidity.summary(conn, date(2026, 9, 10))
    assert s["salary"]["date"] == "2026-09-28" and s["until"] == "2026-09-27"


def test_spending_accounts_are_giro_and_paypal(conn, linked):
    names = {a["name"] for a in liquidity.summary(conn, TODAY)["accounts"]}
    assert names == {"Volksbank Salzburg Gehaltskonto", "PayPal"}       # PayPal USD has no EUR forecast


def test_credit_card_is_always_deducted(conn, linked):
    s = liquidity.summary(conn, TODAY)
    cards = [l for l in s["lines"] if l["kind"] == "card"]
    assert len(cards) == 1 and cards[0]["label"] == "Abrechnung PayLife Classic"
    assert cards[0]["amount"] < 0
    assert cards[0]["date"] > s["until"]                 # due after the salary, still counted


def test_pending_line(conn, linked):
    pending = [l for l in liquidity.summary(conn, TODAY)["lines"] if l["kind"] == "pending"]
    assert pending and pending[0]["amount"] == -2380     # BILLA, pending on the giro account


def test_without_salary_runs_to_period_end(conn, linked):
    conn.execute("UPDATE transactions SET user_category_id=(SELECT id FROM categories WHERE name='Sonstige Einnahmen') "
                 "WHERE description LIKE 'GEHALT%'")
    from finanzen.core.recompute import recompute
    recompute(conn)
    s = liquidity.summary(conn, TODAY)
    assert s["salary"] is None
    assert s["until"] == reports.calendar(conn).period_for(TODAY).end.isoformat()


def test_net_worth_by_kind_adds_up(conn, linked):
    nw = liquidity.summary(conn, TODAY)["net_worth"]
    assert nw["total"] == sum(p["amount"] for p in nw["parts"])
    assert nw["total"] == reports.net_worth(conn, [TODAY])[0]["value"]
    keys = {p["key"]: p for p in nw["parts"]}
    assert keys["cards"]["amount"] < 0
    assert {a["name"] for a in keys["investments"]["accounts"]} == {"flatex Verrechnungskonto"}
    assert nw["not_converted"] == 1                      # PayPal USD without rates
    store_rates(conn, [(TODAY.isoformat(), "USD", "1.2")])
    assert liquidity.summary(conn, TODAY)["net_worth"]["not_converted"] == 0



def test_card_line_explains_the_pending_part(conn, linked):
    s = liquidity.summary(conn, TODAY)
    card = next(l for l in s["lines"] if l["kind"] == "card")
    booked = next(p for p in s["net_worth"]["parts"] if p["key"] == "cards")["amount"]
    # settlement = booked card debt + pending card payments (OMV 54,00 pending in the scenario)
    assert card["pending"] == 5400
    assert -card["amount"] == -booked + card["pending"]
