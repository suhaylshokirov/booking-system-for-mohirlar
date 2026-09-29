"""Small helpers pulled forward for the seed script (see tasks.md deviations)."""

from datetime import UTC, date, datetime, time

import pytest

from app.core.security import hash_password
from app.core.timezones import local_to_utc, utc_to_local


def test_hash_password_is_argon2_and_salted():
    first, second = hash_password("correct horse"), hash_password("correct horse")
    assert first.startswith("$argon2")
    assert "correct horse" not in first
    assert first != second  # random salt


def test_local_to_utc_tashkent_is_five_hours_behind():
    assert local_to_utc(date(2026, 10, 5), time(10, 0), "Asia/Tashkent") == datetime(
        2026, 10, 5, 5, 0, tzinfo=UTC
    )


def test_local_to_utc_can_land_on_the_previous_utc_day():
    assert local_to_utc(date(2026, 10, 5), time(2, 0), "Asia/Tashkent") == datetime(
        2026, 10, 4, 21, 0, tzinfo=UTC
    )


def test_utc_to_local_round_trips_and_rejects_naive_datetimes():
    instant = datetime(2026, 10, 4, 21, 0, tzinfo=UTC)
    assert utc_to_local(instant, "Asia/Tashkent").date() == date(2026, 10, 5)
    with pytest.raises(ValueError):
        utc_to_local(datetime(2026, 10, 4, 21, 0), "Asia/Tashkent")
