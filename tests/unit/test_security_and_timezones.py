"""Small helpers pulled forward for the seed script (see tasks.md deviations)."""

from datetime import UTC, date, datetime, time

import pytest

from app.core.timezones import is_valid_timezone, local_to_utc, utc_to_local


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


@pytest.mark.parametrize("name", ["Asia/Tashkent", "UTC", "America/New_York"])
def test_real_iana_names_are_valid_timezones(name):
    assert is_valid_timezone(name)


@pytest.mark.parametrize("name", ["Mars/Olympus", "Asia", "../etc/passwd", "tashkent", "+05:00"])
def test_anything_else_is_not_a_timezone(name):
    # "Asia" is a directory in the tz database; "../etc/passwd" is a path trick.
    assert not is_valid_timezone(name)
