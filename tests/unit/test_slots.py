"""The pure slot algorithm: build_windows_for_date and compute_slots."""

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace

from app.services.slots import build_windows_for_date, compute_slots

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


# --- compute_slots ---------------------------------------------------------

MIN = timedelta(minutes=1)
LONG_AGO = utc(2026, 1, 1)
FAR_FUTURE = utc(2027, 1, 1)


def slots(windows, busy=(), duration=30, granularity=30, now=LONG_AGO, lead=0, horizon=FAR_FUTURE):
    return compute_slots(windows, busy, duration * MIN, granularity * MIN, now, lead * MIN, horizon)


def hours(*pairs):
    """(hour, minute) pairs -> UTC datetimes on 2026-10-05."""
    return [utc(2026, 10, 5, h, m) for h, m in pairs]


def day(start_h, end_h):
    return (utc(2026, 10, 5, start_h), utc(2026, 10, 5, end_h))


def busy_at(start, end):
    return (utc(2026, 10, 5, *start), utc(2026, 10, 5, *end))


def test_no_windows_means_no_slots():
    assert slots([]) == []


def test_slots_fill_the_window_and_the_last_one_ends_exactly_at_closing():
    assert slots([day(9, 11)]) == hours((9, 0), (9, 30), (10, 0), (10, 30))


def test_a_service_longer_than_the_window_gets_no_slot():
    assert slots([day(9, 10)], duration=90) == []


def test_a_slot_that_would_run_past_closing_is_dropped():
    # 45 min on a 30 min grid: 10:30 would end at 11:15, past the 11:00 close
    assert slots([day(9, 11)], duration=45) == hours((9, 0), (9, 30), (10, 0))


def test_granularity_can_be_finer_than_the_duration():
    assert slots([day(9, 10)], granularity=15) == hours((9, 0), (9, 15), (9, 30))


def test_a_busy_interval_blocks_every_slot_it_overlaps():
    busy = [busy_at((9, 30), (10, 30))]
    assert slots([day(9, 12)], busy) == hours((9, 0), (10, 30), (11, 0), (11, 30))


def test_a_long_service_is_blocked_by_a_booking_inside_its_span():
    busy = [busy_at((10, 0), (10, 30))]
    # 09:00 ends exactly as the booking starts (fine); 09:30 would swallow it
    assert slots([day(9, 12)], busy, duration=60) == hours((9, 0), (10, 30), (11, 0))


def test_busy_intervals_touching_a_slot_boundary_do_not_block_it():
    busy = [busy_at((8, 0), (9, 0)), busy_at((9, 30), (10, 0))]
    assert slots([day(9, 10)], busy) == hours((9, 0))


def test_back_to_back_busy_intervals_leave_the_gap_around_them():
    busy = [busy_at((9, 0), (9, 30)), busy_at((9, 30), (10, 0))]
    assert slots([day(9, 11)], busy) == hours((10, 0), (10, 30))


def test_a_busy_interval_outside_the_window_changes_nothing():
    assert slots([day(9, 10)], [busy_at((20, 0), (21, 0))]) == hours((9, 0), (9, 30))


def test_lead_time_cutoff_is_inclusive():
    now = utc(2026, 10, 5, 8, 30)
    # earliest bookable start is 09:30: 09:00 is too soon, 09:30 exactly is fine
    assert slots([day(9, 11)], now=now, lead=60) == hours((9, 30), (10, 0), (10, 30))


def test_slots_already_in_the_past_are_dropped():
    assert slots([day(9, 11)], now=utc(2026, 10, 5, 10, 0)) == hours((10, 0), (10, 30))


def test_horizon_is_exclusive():
    assert slots([day(9, 11)], horizon=utc(2026, 10, 5, 10, 0)) == hours((9, 0), (9, 30))


def test_a_split_shift_gives_slots_from_both_windows_sorted():
    assert slots([day(13, 14), day(9, 10)]) == hours((9, 0), (9, 30), (13, 0), (13, 30))


def test_overlapping_windows_do_not_duplicate_slots():
    assert slots([day(9, 10), day(9, 11)]) == hours((9, 0), (9, 30), (10, 0), (10, 30))


def test_tashkent_date_gives_slots_in_utc():
    windows = build_windows_for_date([rule(0, (9, 0), (10, 0))], None, MONDAY, TASHKENT)
    assert slots(windows) == hours((4, 0), (4, 30))


def test_a_day_off_gives_no_slots():
    windows = build_windows_for_date([rule(0, (9, 0), (18, 0))], exception(), MONDAY, TASHKENT)
    assert slots(windows) == []


def test_custom_hours_give_slots_only_inside_them():
    windows = build_windows_for_date(
        [rule(0, (9, 0), (18, 0))], exception((12, 0), (13, 0)), MONDAY, TASHKENT
    )
    assert slots(windows) == hours((7, 0), (7, 30))


def test_berlin_spring_forward_day_is_an_hour_shorter():
    sunday = date(2026, 3, 29)  # 02:00 -> 03:00, so 00:00-04:00 local is 3 real hours
    windows = build_windows_for_date([rule(6, (0, 0), (4, 0))], None, sunday, BERLIN)
    assert slots(windows, duration=60, granularity=60) == [
        utc(2026, 3, 28, 23),
        utc(2026, 3, 29, 0),
        utc(2026, 3, 29, 1),
    ]


def test_berlin_fall_back_day_is_an_hour_longer():
    sunday = date(2026, 10, 25)  # 03:00 -> 02:00, so 00:00-04:00 local is 5 real hours
    windows = build_windows_for_date([rule(6, (0, 0), (4, 0))], None, sunday, BERLIN)
    got = slots(windows, duration=60, granularity=60)
    assert len(got) == 5
    assert (got[0], got[-1]) == (utc(2026, 10, 24, 22), utc(2026, 10, 25, 2))
