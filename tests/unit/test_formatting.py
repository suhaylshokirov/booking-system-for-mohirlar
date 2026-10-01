"""How money and durations are printed on pages."""

from datetime import UTC, date, datetime

import pytest

from app.web.formatting import NBSP, day_offset, duration, money, phone, utc_offset


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        (0, "0 UZS"),
        (500, "500 UZS"),
        (60_000, "60 000 UZS"),
        (1_250_000, "1 250 000 UZS"),
    ],
)
def test_money_groups_thousands_with_no_break_spaces(amount, expected):
    assert money(amount, "UZS") == expected.replace(" ", NBSP)


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [
        (15, "15 min"),
        (45, "45 min"),
        (60, "1 h"),
        (75, "1 h 15 min"),
        (120, "2 h"),
    ],
)
def test_duration_reads_as_hours_and_minutes(minutes, expected):
    assert duration(minutes) == expected.replace(" ", NBSP)


# --- utc_offset / day_offset (P10.3) -------------------------------------------------------


@pytest.mark.parametrize(
    ("instant", "zone", "expected"),
    [
        (datetime(2026, 10, 5, 5, tzinfo=UTC), "Asia/Tashkent", "UTC+5"),
        (datetime(2026, 10, 5, 5, tzinfo=UTC), "Asia/Kolkata", "UTC+5:30"),
        (datetime(2026, 10, 5, 5, tzinfo=UTC), "UTC", "UTC+0"),
        (datetime(2026, 10, 5, 5, tzinfo=UTC), "Europe/Berlin", "UTC+2"),  # summer time
        (datetime(2026, 11, 5, 5, tzinfo=UTC), "Europe/Berlin", "UTC+1"),  # winter time
        (datetime(2026, 11, 5, 5, tzinfo=UTC), "America/New_York", "UTC-5"),
        (datetime(2026, 11, 5, 5, tzinfo=UTC), "America/St_Johns", "UTC-3:30"),
    ],
)
def test_utc_offset_follows_the_zone_and_daylight_saving(instant, zone, expected):
    assert utc_offset(instant, zone) == expected


def test_day_offset_is_taken_at_local_noon_on_a_clock_change_day():
    # Berlin's clocks go back at 03:00 on 2026-10-25; by noon it is winter time.
    assert day_offset(date(2026, 10, 25), "Europe/Berlin") == "UTC+1"
    assert day_offset(date(2026, 10, 24), "Europe/Berlin") == "UTC+2"


# --- phone ---------------------------------------------------------------------------------


def test_an_uzbek_number_is_grouped_the_way_it_is_said():
    assert phone("+998901234567") == "+998 90 123 45 67".replace(" ", NBSP)


@pytest.mark.parametrize("number", ["+4930123456", "+12025550123", "+99890123456"])
def test_other_numbers_are_shown_as_stored(number):
    """Grouping is per country; a wrong grouping is worse than none."""
    assert phone(number) == number
