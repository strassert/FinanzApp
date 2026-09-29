from datetime import date, timedelta

from finanzen.core import recurring
from finanzen.core.recompute import recompute
from finanzen.core.recurring import Booking, add_months, detect

from .conftest import TODAY

_ids = iter(range(1, 10_000))


def bk(day, amount, name="", text="", role=None, account=1):
    role = role or ("income" if amount > 0 else "expense")
    return Booking(next(_ids), account, day, amount, role, name, text)


def monthly(first, n, amount, **kw):
    return [bk(add_months(first, i), amount, **kw) for i in range(n)]


def test_monthly_rent_is_recurring():
    found = detect(monthly(date(2026, 3, 1), 7, -95000, name="Hausverwaltung"), TODAY)
    assert len(found) == 1
    r = found[0]
    assert r.interval == "monthly" and r.amount == -95000 and r.monthly == -95000
    assert r.next_date == date(2026, 10, 1) and r.count == 7


def test_two_bookings_are_not_enough_for_monthly():
    assert detect(monthly(date(2026, 8, 1), 2, -95000, name="Hausverwaltung"), TODAY) == []


def test_quarterly_and_yearly():
    quarterly = [bk(add_months(date(2025, 10, 20), 3 * i), -8640, name="Wiener Städtische") for i in range(4)]
    yearly = [bk(date(2024, 3, 2), -12000, text="ORF BEITRAG"), bk(date(2025, 3, 3), -12000, text="ORF BEITRAG")]
    found = {r.name: r for r in detect(quarterly + yearly, TODAY)}
    assert found["Wiener Städtische"].interval == "quarterly"
    assert found["Wiener Städtische"].monthly == -2880
    assert found["ORF BEITRAG"].interval == "yearly"
    assert found["ORF BEITRAG"].next_date == date(2026, 3, 3)


def test_varying_references_in_text_are_one_payee():
    rows = [bk(add_months(date(2026, 4, 15), i), -2490, text=f"A1 RECHNUNG {i}8812{i}") for i in range(5)]
    assert len(detect(rows, TODAY)) == 1


def test_salary_and_bonus_from_same_employer_stay_apart():
    salary = monthly(date(2025, 10, 29), 12, 324000, name="Beispiel Technik GmbH")
    bonus = [bk(date(2026, 6, 29), 215000, name="Beispiel Technik GmbH")]
    found = detect(salary + bonus, TODAY)
    assert [(r.role, r.amount) for r in found] == [("income", 324000)]


def test_price_change_uses_new_amount_and_reports_old():
    rows = monthly(date(2026, 3, 7), 6, -1299, text="NETFLIX.COM") + [bk(date(2026, 9, 7), -1599, text="NETFLIX.COM")]
    [r] = detect(rows, TODAY)
    assert (r.amount, r.previous_amount, r.count) == (-1599, -1299, 7)


def test_prices_creeping_up_stay_one_series():
    rows = [bk(add_months(date(2025, 10, 5), i), -(6000 + i * 600), name="Salzburg AG") for i in range(12)]
    [r] = detect(rows, TODAY)        # 60 -> 126 EUR, each step within 25 %
    assert r.count == 12 and r.previous_amount is None
    assert r.amount == -(6000 + 10 * 600)                  # median of the last three


def test_variable_bill_uses_median_of_last_three():
    amounts = [-2490, -2610, -2490, -2750, -2530]
    rows = [bk(add_months(date(2026, 5, 15), i), a, name="A1") for i, a in enumerate(amounts)]
    [r] = detect(rows, TODAY)
    assert r.amount == -2530 and r.previous_amount is None


def test_irregular_shopping_is_not_recurring():
    days = [1, 3, 9, 10, 17, 24, 25, 30, 44, 51, 52, 60, 75, 79, 90]
    rows = [bk(date(2026, 5, 1) + timedelta(days=d), -(2000 + d * 37 % 1500), text="SPAR DANKT")
            for d in days]
    assert detect(rows, TODAY) == []


def test_two_holiday_visits_a_year_apart_are_not_yearly():
    rows = [bk(date(2025, 8, 5), -2527, text="TESCO METRO"), bk(date(2025, 8, 9), -4410, text="TESCO METRO"),
            bk(date(2026, 8, 5), -2520, text="TESCO METRO")]
    assert detect(rows, TODAY) == []
    changed = [bk(date(2025, 3, 2), -12000, text="ORF BEITRAG"), bk(date(2026, 3, 3), -15000, text="ORF BEITRAG")]
    assert detect(changed, TODAY) == []


def test_ended_series_is_dropped_and_refunds_ignored():
    ended = monthly(date(2025, 1, 5), 6, -999, text="FITNESSSTUDIO")
    refund = [bk(add_months(date(2026, 3, 9), i), 500, text="ERSTATTUNG", role="expense") for i in range(6)]
    assert detect(ended + refund, TODAY) == []


def test_overdue_payment_is_still_active():
    rows = monthly(date(2026, 3, 20), 6, -3850, name="UNIQA")      # last 20 Aug, next 20 Sep
    [r] = detect(rows, TODAY)
    assert r.next_date == date(2026, 9, 20) and r.next_date < TODAY


# --- with the fake bank -------------------------------------------------------------

def test_scenario_fixed_costs(conn, linked):
    data = recurring.overview(conn, TODAY)
    names = {i["name"]: i for i in data["items"]}
    assert names["Hausverwaltung Sonnenhof"]["amount"] == -95000
    assert names["Hausverwaltung Sonnenhof"]["category"]["name"] == "Wohnen"
    assert names["Salzburg AG"]["interval"] == "monthly"
    assert names["Beispiel Technik GmbH"]["role"] == "income"
    assert not any("Zalando" in n or "Valve" in n for n in names)   # random amounts
    assert all(i["role"] in ("expense", "income") for i in data["items"])   # no transfers
    assert data["monthly_expense"] == -sum(i["monthly"] for i in data["items"] if i["role"] == "expense")


def test_rejection_survives_recompute(conn, linked):
    key = next(i["key"] for i in recurring.overview(conn, TODAY)["items"] if i["name"] == "Salzburg AG")
    before = recurring.overview(conn, TODAY)["monthly_expense"]
    recurring.decide(conn, key, "rejected")
    recompute(conn)
    data = recurring.overview(conn, TODAY)
    assert key not in {i["key"] for i in data["items"]}
    assert [i["key"] for i in data["rejected"]] == [key]
    assert data["monthly_expense"] == before - 6840
    recurring.decide(conn, key, None)
    assert key in {i["key"] for i in recurring.overview(conn, TODAY)["items"]}
