"""How money and durations are printed on pages."""

import pytest

from app.web.formatting import NBSP, duration, money


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
