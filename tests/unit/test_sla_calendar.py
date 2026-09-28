from datetime import UTC, date, datetime, timedelta

import pytest

from apps.sla.calendar import (
    DHAKA,
    Calendar,
    add_working_days,
    due_at,
    paused_working_days,
)

OPEN = Calendar()
SUNDAY = date(2026, 9, 27)  # Sunday is the first working day of the Bangladeshi week


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=DHAKA)


def test_friday_and_saturday_are_the_weekend():
    week = [SUNDAY + timedelta(days=i) for i in range(7)]
    assert [OPEN.is_working(d) for d in week] == [True] * 5 + [False, False]


def test_the_start_day_never_counts_whatever_the_hour():
    assert add_working_days(OPEN, SUNDAY, 1) == SUNDAY + timedelta(days=1)
    assert due_at(OPEN, at(SUNDAY, 9), 1) == due_at(OPEN, at(SUNDAY, 16, 55), 1)


def test_counting_skips_the_weekend():
    thursday = SUNDAY + timedelta(days=4)
    assert add_working_days(OPEN, thursday, 1) == SUNDAY + timedelta(days=7)  # next Sunday


def test_counting_skips_holidays():
    monday = SUNDAY + timedelta(days=1)
    calendar = Calendar({monday})
    assert add_working_days(calendar, SUNDAY, 1) == SUNDAY + timedelta(days=2)


def test_a_filing_on_the_weekend_starts_counting_on_sunday():
    friday = SUNDAY - timedelta(days=2)
    assert add_working_days(OPEN, friday, 1) == SUNDAY


def test_the_deadline_is_the_end_of_the_day_in_dhaka():
    deadline = due_at(OPEN, at(SUNDAY, 10), 7)
    assert deadline.astimezone(DHAKA).date() == date(2026, 10, 6)  # Tuesday of the next week
    assert (deadline.hour, deadline.minute, deadline.second) == (23, 59, 59)
    assert deadline.utcoffset() == timedelta(hours=6)


def test_the_day_is_the_dhaka_day_not_the_utc_day():
    # 19:30 UTC on Saturday is 01:30 on Sunday in Dhaka: Sunday is the start day.
    late_saturday_utc = datetime(2026, 9, 26, 19, 30, tzinfo=UTC)
    assert due_at(OPEN, late_saturday_utc, 1).date() == SUNDAY + timedelta(days=1)


def test_year_boundary():
    new_years_eve = date(2026, 12, 31)  # Thursday
    calendar = Calendar({date(2027, 1, 3)})  # a holiday on the first Sunday
    assert add_working_days(calendar, new_years_eve, 1) == date(2027, 1, 4)


def test_pauses_count_working_time_rounded_up():
    monday = SUNDAY + timedelta(days=1)
    assert paused_working_days(OPEN, [(at(monday, 10), at(monday, 10, 5))]) == 1
    assert paused_working_days(OPEN, [(at(monday, 10), at(monday + timedelta(days=1), 10))]) == 1
    assert paused_working_days(OPEN, [(at(monday, 10), at(monday + timedelta(days=1), 11))]) == 2


def test_weekend_hours_in_a_pause_are_free():
    thursday_evening = at(SUNDAY + timedelta(days=4), 23)
    sunday_morning = at(SUNDAY + timedelta(days=7), 1)
    assert paused_working_days(OPEN, [(thursday_evening, sunday_morning)]) == 1  # 2 working hours


def test_a_pause_moves_the_deadline():
    monday = SUNDAY + timedelta(days=1)
    pause = (at(monday, 10), at(monday + timedelta(days=2), 10))  # two working days
    assert due_at(OPEN, at(SUNDAY, 9), 7, [pause]) == due_at(OPEN, at(SUNDAY, 9), 9)


def test_a_calendar_with_no_working_days_is_an_error_not_a_hang():
    every_day = Calendar(SUNDAY + timedelta(days=i) for i in range(4000))
    with pytest.raises(ValueError, match="working days"):
        add_working_days(every_day, SUNDAY, 1)
