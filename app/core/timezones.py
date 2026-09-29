"""Local wall-clock time <-> UTC instants: the one module that does it.

Availability is stored as local times in the business timezone; bookings are
UTC instants. Every conversion between the two goes through this module and
uses `zoneinfo`, so the DST policy lives in one place (ADR 0006).

Only `local_to_utc` and `utc_to_local` exist so far, because the seed script needs it (see the
Deviations log). P4.1 adds window and day-bound helpers and the documented DST
gap/overlap policy.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo


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
