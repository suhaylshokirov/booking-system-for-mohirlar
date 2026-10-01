"""Local wall-clock time <-> UTC instants: the one module that does it.

Availability is stored as local times in the business timezone; bookings are
UTC instants. Every conversion between the two goes through this module and
uses `zoneinfo`, so the DST policy lives in one place (ADR 0006).

DST policy, for the two kinds of local time that daylight saving breaks:

- **Gap** (spring forward, e.g. 02:30 on 2026-03-29 in `Europe/Berlin` never
  happens): the time is moved *forward* to the first instant that exists, the
  moment the clocks jump (03:00). Shifting by the gap length instead (02:30 ->
  03:30) would let a window that ends at 02:30 run half an hour past what the
  barber wrote.
- **Overlap** (fall back, e.g. 02:30 on 2026-10-25 happens twice): the *first*
  occurrence wins (`fold=0`, still summer time).

Uzbekistan has no DST, so for `Asia/Tashkent` none of this ever triggers.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def is_valid_timezone(name: str) -> bool:
    """Whether `name` is an IANA zone name such as `Asia/Tashkent`.

    Asks `zoneinfo` itself, so "valid" means exactly "we can convert with it".
    A name that is not a plain zone key (`../etc/passwd`, a directory such as
    `Asia`) makes `ZoneInfo` raise `ValueError` or `OSError` rather than
    `ZoneInfoNotFoundError`, so all three count as invalid.
    """
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return False
    return True


def local_to_utc(day: date, at: time, timezone: str) -> datetime:
    """The UTC instant at which the clock in `timezone` shows `day` `at`.

    A time inside a DST gap is moved forward to the first valid instant; an
    ambiguous time takes its first occurrence (see the module docstring).

    Raises:
        zoneinfo.ZoneInfoNotFoundError: `timezone` is not an IANA zone name.
    """
    zone = ZoneInfo(timezone)
    wall = datetime.combine(day, at.replace(tzinfo=None))
    # `fold=0` (the default) already picks the first occurrence of an
    # ambiguous time. For a gap it applies the offset from *before* the jump,
    # which lands after the jump; that is the case handled below.
    candidate = wall.replace(tzinfo=zone).astimezone(UTC)
    if candidate.astimezone(zone).replace(tzinfo=None) == wall:
        return candidate
    return _first_instant_after_gap(wall, zone)


def _first_instant_after_gap(wall: datetime, zone: ZoneInfo) -> datetime:
    """The instant the clocks jump forward over the nonexistent time `wall`.

    `wall` read with the offset from before the jump is a *later* instant than
    `wall` read with the offset from after it; the jump lies between the two.
    Bisecting down to the second finds it exactly.
    """
    earlier = wall.replace(tzinfo=zone, fold=1).astimezone(UTC)
    later = wall.replace(tzinfo=zone, fold=0).astimezone(UTC)
    offset_before_jump = earlier.astimezone(zone).utcoffset()
    while later - earlier > timedelta(seconds=1):
        middle = earlier + (later - earlier) / 2
        if middle.astimezone(zone).utcoffset() == offset_before_jump:
            earlier = middle
        else:
            later = middle
    return later


def local_window_to_utc(
    day: date, start_time: time, end_time: time, timezone: str
) -> tuple[datetime, datetime]:
    """A local working window `[start_time, end_time)` on `day`, as UTC instants.

    Both ends follow the DST policy of `local_to_utc`. On a DST day the result
    can be an hour shorter or longer than the wall-clock difference, and a
    window lying entirely inside a gap comes back empty (start == end).

    Raises:
        ValueError: `end_time` is not after `start_time`. Windows never cross
            midnight, and the schemas reject such input before it gets here.
        zoneinfo.ZoneInfoNotFoundError: `timezone` is not an IANA zone name.
    """
    if end_time <= start_time:
        raise ValueError("a window must end after it starts")
    return (
        local_to_utc(day, start_time, timezone),
        local_to_utc(day, end_time, timezone),
    )


def local_day_bounds_utc(day: date, timezone: str) -> tuple[datetime, datetime]:
    """The UTC instants of local midnight starting `day` and starting the next day.

    A half-open range `[start, end)` covering exactly that local date. It is
    23 or 25 hours long on a DST day, and never the same as the UTC date: in
    Tashkent, 2026-10-05 begins at 19:00 UTC on 2026-10-04.

    Raises:
        zoneinfo.ZoneInfoNotFoundError: `timezone` is not an IANA zone name.
    """
    return (
        local_to_utc(day, time(0, 0), timezone),
        local_to_utc(day + timedelta(days=1), time(0, 0), timezone),
    )


def utc_to_local(instant: datetime, timezone: str) -> datetime:
    """`instant` expressed on the clock of `timezone`.

    Raises:
        ValueError: `instant` is timezone-naive (its meaning would be a guess).
        zoneinfo.ZoneInfoNotFoundError: `timezone` is not an IANA zone name.
    """
    if instant.tzinfo is None:
        raise ValueError("utc_to_local needs a timezone-aware datetime")
    return instant.astimezone(ZoneInfo(timezone))
