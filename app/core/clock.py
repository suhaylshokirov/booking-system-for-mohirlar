"""The injectable clock.

Business logic never calls `datetime.now()`: it takes `now` from a `Clock`, so
tests can freeze time and check lead-time, horizon and cancellation-cutoff
rules exactly at their boundaries. Every instant is timezone-aware UTC.
"""

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """The current instant, timezone-aware, in UTC."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """A clock that only moves when the test tells it to."""

    def __init__(self, at: datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FrozenClock needs a timezone-aware datetime")
        self._at = at.astimezone(UTC)

    def now(self) -> datetime:
        return self._at

    def advance(self, delta: timedelta) -> None:
        self._at += delta


def get_clock() -> Clock:
    """FastAPI dependency. Tests override it with a `FrozenClock`."""
    return SystemClock()
