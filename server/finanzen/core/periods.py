"""Budget periods: calendar months (default) or from salary to salary.

Calendar months: a salary booked in the last 10 days of a month counts for
the next month (salary on 29 Sep is the money for October), see
`budget_day`.

Salary to salary (setting salary_day): period M nominally starts on the
salary day of the previous month. A salary booking from 10 days before to 5
days after that nominal day moves the start to its booking date. A period
is named after the month it mostly covers (salary on 28 Sep -> "Oktober").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Iterable, Optional

MONTHS_DE = ["Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
             "September", "Oktober", "November", "Dezember"]

EARLY_DAYS = 10
LATE_DAYS = 5


@dataclass(frozen=True)
class Period:
    year: int
    month: int            # the month the period is named after
    start: date
    end: date             # inclusive

    @property
    def key(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @property
    def label(self) -> str:
        return f"{MONTHS_DE[self.month - 1]} {self.year}"

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def budget_day(day: date, is_salary: bool, calendar_months: bool) -> date:
    """The day a booking counts for in budget periods."""
    if not (is_salary and calendar_months):
        return day
    ny, nm = _next_month(day.year, day.month)
    first_next = date(ny, nm, 1)
    return first_next if (first_next - day).days <= EARLY_DAYS else day


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _clamped(year: int, month: int, day: int) -> date:
    ny, nm = _next_month(year, month)
    last = (date(ny, nm, 1) - timedelta(days=1)).day
    return date(year, month, min(day, last))


class PeriodCalendar:
    def __init__(self, salary_day: Optional[int], salary_dates: Iterable[date] = ()):
        """salary_day None = calendar months."""
        self.salary_day = salary_day
        self.salary_dates = sorted(set(salary_dates))

    def start_of(self, year: int, month: int) -> date:
        if not self.salary_day:
            return date(year, month, 1)
        py, pm = _prev_month(year, month)
        nominal = _clamped(py, pm, self.salary_day)
        window = [d for d in self.salary_dates
                  if nominal - timedelta(days=EARLY_DAYS) <= d <= nominal + timedelta(days=LATE_DAYS)]
        if window:
            # the salary closest to the nominal day wins
            return min(window, key=lambda d: (abs((d - nominal).days), d))
        return nominal

    def period(self, year: int, month: int) -> Period:
        ny, nm = _next_month(year, month)
        return Period(year, month, self.start_of(year, month), self.start_of(ny, nm) - timedelta(days=1))

    def period_for(self, day: date) -> Period:
        # The period named after month M may start in M-1; check M and M+1.
        for y, m in (_next_month(day.year, day.month), (day.year, day.month),
                     _prev_month(day.year, day.month)):
            p = self.period(y, m)
            if p.contains(day):
                return p
        raise AssertionError(f"no period for {day}")  # unreachable with sane windows

    def previous(self, period: Period) -> Period:
        return self.period(*_prev_month(period.year, period.month))

    def next(self, period: Period) -> Period:
        return self.period(*_next_month(period.year, period.month))

    def range(self, first: date, last: date) -> list[Period]:
        out = []
        p = self.period_for(first)
        while p.start <= last:
            out.append(p)
            p = self.next(p)
        return out
