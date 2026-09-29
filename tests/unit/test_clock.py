from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.core.clock import FrozenClock, SystemClock


def test_system_clock_returns_timezone_aware_utc():
    now = SystemClock().now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_frozen_clock_stays_put_until_advanced():
    clock = FrozenClock(datetime(2026, 10, 1, 9, 0, tzinfo=UTC))
    assert clock.now() == clock.now() == datetime(2026, 10, 1, 9, 0, tzinfo=UTC)

    clock.advance(timedelta(minutes=30))

    assert clock.now() == datetime(2026, 10, 1, 9, 30, tzinfo=UTC)


def test_frozen_clock_rejects_naive_datetime():
    with pytest.raises(ValueError):
        FrozenClock(datetime(2026, 10, 1, 9, 0))


def test_frozen_clock_normalises_to_utc():
    tashkent = timezone(timedelta(hours=5))
    clock = FrozenClock(datetime(2026, 10, 1, 14, 0, tzinfo=tashkent))
    assert clock.now() == datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
    assert clock.now().utcoffset() == timedelta(0)
