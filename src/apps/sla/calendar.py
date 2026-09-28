"""Working-day deadlines (design §5.3). Pure functions: no database, no clock.

A deadline is the end of the Nth working day after the day the clock started, in Bangladesh
time. The start day never counts, whatever the hour: a request filed at 16:55 on a Sunday has
the same deadline as one filed at 09:00. Time the request spent waiting on the citizen moves
the deadline by that many working days, rounded up.
"""

import math
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DHAKA = ZoneInfo("Asia/Dhaka")
WEEKEND = frozenset({4, 5})  # Friday and Saturday (Monday is 0)
# No real deadline is three years away. Reaching this means the calendar closes every day,
# which is a data error to report, not a loop to run forever.
MAX_SPAN_DAYS = 3 * 366
_DAY = timedelta(days=1)


class Calendar:
    def __init__(self, closed: Iterable[date] = ()):
        self.closed = frozenset(closed)  # holidays and suspended days

    def is_working(self, day: date) -> bool:
        return day.weekday() not in WEEKEND and day not in self.closed


def local_date(moment: datetime) -> date:
    return moment.astimezone(DHAKA).date()


def day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, DHAKA)


def end_of_day(day: date) -> datetime:
    return datetime.combine(day, time(23, 59, 59), DHAKA)


def add_working_days(calendar: Calendar, start: date, n: int) -> date:
    """The nth working day after `start`."""
    if n < 1:
        raise ValueError("n must be positive")
    day = start
    for _ in range(MAX_SPAN_DAYS):
        day += _DAY
        if calendar.is_working(day):
            n -= 1
            if n == 0:
                return day
    raise ValueError(f"fewer than {n} working days within {MAX_SPAN_DAYS} days of {start}")


def paused_working_days(calendar: Calendar, pauses: Iterable[tuple[datetime, datetime]]) -> int:
    """Working time inside the pauses, in days, rounded up. Weekend and holiday hours are free:
    the clock was not running then anyway."""
    seconds = 0.0
    for started, ended in pauses:
        day, last = local_date(started), local_date(ended)
        while day <= last:
            if calendar.is_working(day):
                overlap = min(ended, day_start(day + _DAY)) - max(started, day_start(day))
                seconds += max(overlap.total_seconds(), 0.0)
            day += _DAY
    return math.ceil(seconds / 86400)


def due_at(
    calendar: Calendar,
    started_at: datetime,
    target_working_days: int,
    pauses: Iterable[tuple[datetime, datetime]] = (),
) -> datetime:
    days = target_working_days + paused_working_days(calendar, pauses)
    return end_of_day(add_working_days(calendar, local_date(started_at), days))
