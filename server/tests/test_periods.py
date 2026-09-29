from datetime import date

from finanzen.core.periods import PeriodCalendar, budget_day


def test_nominal_period_without_salary():
    cal = PeriodCalendar(29)
    p = cal.period(2026, 10)
    assert (p.start, p.end) == (date(2026, 9, 29), date(2026, 10, 28))
    assert p.label == "Oktober 2026"


def test_salary_on_28th_names_next_month():
    cal = PeriodCalendar(29, [date(2026, 9, 28)])
    p = cal.period_for(date(2026, 9, 28))
    assert p.label == "Oktober 2026" and p.start == date(2026, 9, 28)
    assert cal.period_for(date(2026, 9, 27)).label == "September 2026"


def test_salary_window_ten_days_before_five_after():
    cal = PeriodCalendar(29, [date(2026, 5, 19)])
    assert cal.start_of(2026, 6) == date(2026, 5, 19)       # 10 days early -> moves start
    cal = PeriodCalendar(29, [date(2026, 5, 18)])
    assert cal.start_of(2026, 6) == date(2026, 5, 29)       # 11 days early -> ignored
    cal = PeriodCalendar(29, [date(2026, 8, 3)])
    assert cal.start_of(2026, 8) == date(2026, 8, 3)        # 5 days late -> moves start
    cal = PeriodCalendar(29, [date(2026, 8, 4)])
    assert cal.start_of(2026, 8) == date(2026, 7, 29)       # 6 days late -> ignored


def test_late_salary_extends_previous_period():
    cal = PeriodCalendar(29, [date(2026, 8, 28), date(2026, 10, 2)])
    oct_ = cal.period(2026, 10)
    assert oct_.start == date(2026, 10, 2)
    assert cal.period(2026, 9).end == date(2026, 10, 1)


def test_february_clamps_nominal_day():
    cal = PeriodCalendar(29)
    assert cal.start_of(2026, 3) == date(2026, 2, 28)
    assert cal.start_of(2028, 3) == date(2028, 2, 29)


def test_periods_are_contiguous():
    cal = PeriodCalendar(29, [date(2026, 1, 29), date(2026, 2, 27), date(2026, 3, 27), date(2026, 4, 29)])
    periods = cal.range(date(2026, 1, 1), date(2026, 6, 30))
    for a, b in zip(periods, periods[1:]):
        assert (b.start - a.end).days == 1


def test_calendar_months_without_salary_day():
    cal = PeriodCalendar(None)
    p = cal.period_for(date(2026, 9, 28))
    assert (p.start, p.end, p.label) == (date(2026, 9, 1), date(2026, 9, 30), "September 2026")


def test_budget_day_moves_late_salary_to_next_month():
    assert budget_day(date(2026, 9, 29), True, True) == date(2026, 10, 1)
    assert budget_day(date(2026, 9, 21), True, True) == date(2026, 10, 1)      # 10 days before the 1st
    assert budget_day(date(2026, 9, 20), True, True) == date(2026, 9, 20)
    assert budget_day(date(2026, 10, 1), True, True) == date(2026, 10, 1)      # "spätestens am 1."
    assert budget_day(date(2026, 12, 30), True, True) == date(2027, 1, 1)
    assert budget_day(date(2026, 9, 29), False, True) == date(2026, 9, 29)     # not a salary
    assert budget_day(date(2026, 9, 29), True, False) == date(2026, 9, 29)     # salary-to-salary mode
