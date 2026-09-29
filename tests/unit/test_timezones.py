"""The timezone module: Tashkent (no DST) and Europe/Berlin (DST) day by day."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from pydantic import BaseModel, ValidationError

from app.core.timezones import (
    local_day_bounds_utc,
    local_to_utc,
    local_window_to_utc,
    utc_to_local,
)
from app.schemas.types import UtcDatetime

TASHKENT = "Asia/Tashkent"
BERLIN = "Europe/Berlin"

# Berlin 2026: clocks jump 02:00 -> 03:00 on 29 March and back 03:00 -> 02:00
# on 25 October; both at 01:00 UTC.
SPRING_FORWARD = date(2026, 3, 29)
FALL_BACK = date(2026, 10, 25)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


# --- Tashkent: UTC+5 all year -------------------------------------------------


def test_tashkent_window_is_five_hours_behind_utc():
    start, end = local_window_to_utc(date(2026, 10, 5), time(9, 0), time(18, 0), TASHKENT)
    assert (start, end) == (utc(2026, 10, 5, 4, 0), utc(2026, 10, 5, 13, 0))


def test_tashkent_local_date_starts_on_the_previous_utc_day():
    # 02:00 on the 5th in Tashkent is 21:00 on the 4th in UTC.
    assert local_to_utc(date(2026, 10, 5), time(2, 0), TASHKENT) == utc(2026, 10, 4, 21, 0)
    start, end = local_day_bounds_utc(date(2026, 10, 5), TASHKENT)
    assert (start, end) == (utc(2026, 10, 4, 19, 0), utc(2026, 10, 5, 19, 0))


def test_tashkent_days_are_always_24_hours():
    for day in (date(2026, 3, 29), date(2026, 10, 25)):
        start, end = local_day_bounds_utc(day, TASHKENT)
        assert end - start == timedelta(hours=24)


def test_utc_to_local_moves_the_date_forward_in_tashkent():
    local = utc_to_local(utc(2026, 10, 4, 21, 0), TASHKENT)
    assert (local.date(), local.time()) == (date(2026, 10, 5), time(2, 0))


def test_utc_to_local_rejects_naive_datetimes():
    with pytest.raises(ValueError):
        utc_to_local(datetime(2026, 10, 4, 21, 0), TASHKENT)


# --- Berlin: an ordinary day, summer and winter -------------------------------


def test_berlin_offset_changes_between_winter_and_summer():
    assert local_to_utc(date(2026, 1, 15), time(9, 0), BERLIN) == utc(2026, 1, 15, 8, 0)
    assert local_to_utc(date(2026, 7, 15), time(9, 0), BERLIN) == utc(2026, 7, 15, 7, 0)


# --- Berlin: spring forward (a local time that never happens) -----------------


def test_spring_forward_gap_time_moves_to_the_first_valid_instant():
    # 02:00-03:00 does not exist. 02:30 becomes 03:00 CEST = 01:00 UTC, the
    # instant the clocks jump - not 03:30, which zoneinfo would pick by default.
    assert local_to_utc(SPRING_FORWARD, time(2, 30), BERLIN) == utc(2026, 3, 29, 1, 0)


def test_spring_forward_edges_of_the_gap():
    # 02:00 is the first nonexistent minute; 03:00 is the first that exists again.
    assert local_to_utc(SPRING_FORWARD, time(2, 0), BERLIN) == utc(2026, 3, 29, 1, 0)
    assert local_to_utc(SPRING_FORWARD, time(3, 0), BERLIN) == utc(2026, 3, 29, 1, 0)
    assert local_to_utc(SPRING_FORWARD, time(1, 59), BERLIN) == utc(2026, 3, 29, 0, 59)


def test_spring_forward_window_across_the_gap_is_one_hour_shorter():
    start, end = local_window_to_utc(SPRING_FORWARD, time(1, 0), time(5, 0), BERLIN)
    assert end - start == timedelta(hours=3)  # 4 wall-clock hours, 3 real ones


def test_window_ending_inside_the_gap_does_not_run_past_it():
    start, end = local_window_to_utc(SPRING_FORWARD, time(1, 0), time(2, 30), BERLIN)
    assert end == utc(2026, 3, 29, 1, 0)
    assert end - start == timedelta(hours=1)


def test_window_lying_wholly_inside_the_gap_is_empty():
    start, end = local_window_to_utc(SPRING_FORWARD, time(2, 15), time(2, 45), BERLIN)
    assert start == end


def test_spring_forward_day_is_23_hours_long():
    start, end = local_day_bounds_utc(SPRING_FORWARD, BERLIN)
    assert end - start == timedelta(hours=23)
    assert start == utc(2026, 3, 28, 23, 0)  # midnight CET


# --- Berlin: fall back (a local time that happens twice) ----------------------


def test_fall_back_ambiguous_time_takes_the_first_occurrence():
    # 02:30 happens at 00:30 UTC (CEST, +2) and again at 01:30 UTC (CET, +1).
    assert local_to_utc(FALL_BACK, time(2, 30), BERLIN) == utc(2026, 10, 25, 0, 30)


def test_fall_back_times_outside_the_overlap_are_unambiguous():
    assert local_to_utc(FALL_BACK, time(1, 59), BERLIN) == utc(2026, 10, 24, 23, 59)
    assert local_to_utc(FALL_BACK, time(3, 0), BERLIN) == utc(2026, 10, 25, 2, 0)


def test_fall_back_window_across_the_overlap_is_one_hour_longer():
    start, end = local_window_to_utc(FALL_BACK, time(1, 0), time(5, 0), BERLIN)
    assert end - start == timedelta(hours=5)  # 4 wall-clock hours, 5 real ones


def test_fall_back_day_is_25_hours_long():
    start, end = local_day_bounds_utc(FALL_BACK, BERLIN)
    assert end - start == timedelta(hours=25)


def test_consecutive_days_tile_without_a_hole_or_overlap():
    day = date(2026, 3, 27)
    previous_end = local_day_bounds_utc(day, BERLIN)[1]
    for _ in range(5):  # across the spring-forward night
        day += timedelta(days=1)
        start, end = local_day_bounds_utc(day, BERLIN)
        assert start == previous_end
        previous_end = end


# --- Errors -------------------------------------------------------------------


@pytest.mark.parametrize("end", [time(9, 0), time(8, 0)])
def test_window_must_end_after_it_starts(end):
    with pytest.raises(ValueError):
        local_window_to_utc(date(2026, 10, 5), time(9, 0), end, TASHKENT)


# --- Schema type: naive datetimes are rejected --------------------------------


class _Body(BaseModel):
    at: UtcDatetime


def test_schema_rejects_a_naive_datetime():
    with pytest.raises(ValidationError):
        _Body(at="2026-10-05T10:00:00")


def test_schema_converts_any_offset_to_utc():
    body = _Body(at="2026-10-05T10:00:00+05:00")
    assert body.at == utc(2026, 10, 5, 5, 0)
    assert body.at.utcoffset() == timedelta(0)
    assert _Body(at="2026-10-05T05:00:00Z").at == body.at
