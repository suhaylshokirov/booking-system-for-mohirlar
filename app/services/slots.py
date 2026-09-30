"""Slot computation: pure functions, no database, no clock.

`build_windows_for_date` turns a provider's rules/exception into UTC working
windows (pulled forward from P5.1 because P4.4 needs it, see the Deviations
log); `compute_slots` lays a service-sized grid over those windows and removes
what is busy, too soon or too far ahead. `now` is always passed in.

This grid is advisory: the exclusion constraints in the database decide who
actually gets a slot (ADR 0001).
"""

from collections.abc import Iterable
from datetime import date, datetime, timedelta

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


def compute_slots(
    windows_utc: Iterable[tuple[datetime, datetime]],
    busy_utc: Iterable[tuple[datetime, datetime]],
    duration: timedelta,
    granularity: timedelta,
    now: datetime,
    lead_time: timedelta,
    horizon_end: datetime,
) -> list[datetime]:
    """Bookable start instants (UTC, sorted, unique) for one provider and one service.

    Candidates step by `granularity` from each window's start. A candidate
    `start` is kept iff all of these hold:

    - `[start, start + duration)` lies entirely inside one window, so a
      service that does not fit before closing time gets no slot;
    - it overlaps no busy interval. Ranges are half-open, so a booking that
      ends exactly at `start`, or starts exactly at `start + duration`, does
      not block it (back-to-back is allowed);
    - `start >= now + lead_time` (inclusive: exactly at the cut-off is fine);
    - `start < horizon_end` (exclusive).

    All datetimes must be timezone-aware. Never raises for empty input.
    """
    earliest = now + lead_time
    busy = list(busy_utc)
    starts: set[datetime] = set()
    for window_start, window_end in windows_utc:
        start = window_start
        while start + duration <= window_end:
            end = start + duration
            if earliest <= start < horizon_end and not _overlaps_any(start, end, busy):
                starts.add(start)
            start += granularity
    return sorted(starts)


def _overlaps_any(start: datetime, end: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
    """Half-open overlap test: two ranges clash iff each starts before the other ends."""
    return any(busy_start < end and start < busy_end for busy_start, busy_end in busy)
