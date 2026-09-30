"""Slot computation: pure functions, no database, no clock.

So far only `build_windows_for_date`, pulled forward from P5.1 because P4.4
needs it to tell whether a booking still fits inside the provider's hours
(see the Deviations log). P5.1 adds `compute_slots` beside it.
"""

from collections.abc import Iterable
from datetime import date, datetime

from app.core.timezones import local_window_to_utc


def build_windows_for_date(
    rules: Iterable, exception: object | None, day: date, timezone: str
) -> list[tuple[datetime, datetime]]:
    """The provider's working windows on local date `day`, as sorted UTC `[start, end)` pairs.

    An exception for the date **replaces** the weekly rules entirely: a day off
    (no times) gives no windows, custom hours give exactly one. Without an
    exception, every rule whose weekday is `day`'s weekday gives one window.
    Windows that collapse to nothing (wholly inside a DST gap) are dropped.

    `rules` need `weekday`, `start_time`, `end_time`; `exception` needs
    `start_time`, `end_time` (both None for a day off).
    """
    if exception is not None:
        if exception.start_time is None:
            return []
        local_windows = [(exception.start_time, exception.end_time)]
    else:
        local_windows = [
            (rule.start_time, rule.end_time) for rule in rules if rule.weekday == day.weekday()
        ]
    windows = [local_window_to_utc(day, start, end, timezone) for start, end in local_windows]
    return sorted(window for window in windows if window[0] < window[1])
