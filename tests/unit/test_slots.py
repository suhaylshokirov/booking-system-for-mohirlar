"""build_windows_for_date: the pure part of slot computation (P5.1 adds compute_slots)."""

from datetime import UTC, date, datetime, time
from types import SimpleNamespace

from app.services.slots import build_windows_for_date

TASHKENT, BERLIN = "Asia/Tashkent", "Europe/Berlin"
MONDAY = date(2026, 10, 5)


def rule(weekday, start, end):
    return SimpleNamespace(weekday=weekday, start_time=time(*start), end_time=time(*end))


def exception(start=None, end=None):
    return SimpleNamespace(
        start_time=None if start is None else time(*start),
        end_time=None if end is None else time(*end),
    )


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def test_no_rules_means_no_windows():
    assert build_windows_for_date([], None, MONDAY, TASHKENT) == []


def test_only_rules_for_that_weekday_count_and_come_back_in_utc():
    rules = [rule(0, (9, 0), (13, 0)), rule(1, (9, 0), (18, 0))]
    assert build_windows_for_date(rules, None, MONDAY, TASHKENT) == [
        (utc(2026, 10, 5, 4), utc(2026, 10, 5, 8))
    ]


def test_a_split_shift_gives_two_sorted_windows():
    rules = [rule(0, (14, 0), (18, 0)), rule(0, (9, 0), (12, 0))]
    assert build_windows_for_date(rules, None, MONDAY, TASHKENT) == [
        (utc(2026, 10, 5, 4), utc(2026, 10, 5, 7)),
        (utc(2026, 10, 5, 9), utc(2026, 10, 5, 13)),
    ]


def test_a_day_off_exception_removes_the_rules():
    assert build_windows_for_date([rule(0, (9, 0), (18, 0))], exception(), MONDAY, TASHKENT) == []


def test_custom_hours_replace_the_rules_instead_of_adding_to_them():
    rules = [rule(0, (9, 0), (18, 0))]
    assert build_windows_for_date(rules, exception((12, 0), (16, 0)), MONDAY, TASHKENT) == [
        (utc(2026, 10, 5, 7), utc(2026, 10, 5, 11))
    ]


def test_custom_hours_apply_even_on_a_weekday_without_rules():
    assert build_windows_for_date([], exception((12, 0), (16, 0)), MONDAY, TASHKENT) == [
        (utc(2026, 10, 5, 7), utc(2026, 10, 5, 11))
    ]


def test_a_window_wholly_inside_a_dst_gap_is_dropped():
    sunday = date(2026, 3, 29)  # Berlin springs forward 02:00 -> 03:00
    rules = [rule(6, (2, 15), (2, 45)), rule(6, (9, 0), (12, 0))]
    assert build_windows_for_date(rules, None, sunday, BERLIN) == [
        (utc(2026, 3, 29, 7), utc(2026, 3, 29, 10))
    ]
