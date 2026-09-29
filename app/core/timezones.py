"""Local wall-clock time <-> UTC instants: the one module that does it.

Availability is stored as local times in the business timezone; bookings are
UTC instants. Every conversion between the two goes through this module and
uses `zoneinfo`, so the DST policy lives in one place (ADR 0006).

Only `is_valid_timezone`, `local_to_utc` and `utc_to_local` exist so far (the
seed script needs the last two; see the Deviations log). P4.1 adds window and
day-bound helpers and the documented DST gap/overlap policy.
"""

from datetime import UTC, date, datetime, time
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

    Raises:
        zoneinfo.ZoneInfoNotFoundError: `timezone` is not an IANA zone name.
    """
    local = datetime.combine(day, at, tzinfo=ZoneInfo(timezone))
    return local.astimezone(UTC)


def utc_to_local(instant: datetime, timezone: str) -> datetime:
    """`instant` expressed on the clock of `timezone`.

    Raises:
        ValueError: `instant` is timezone-naive (its meaning would be a guess).
        zoneinfo.ZoneInfoNotFoundError: `timezone` is not an IANA zone name.
    """
    if instant.tzinfo is None:
        raise ValueError("utc_to_local needs a timezone-aware datetime")
    return instant.astimezone(ZoneInfo(timezone))
