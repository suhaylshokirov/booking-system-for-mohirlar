"""One test per booking-rule code, plus the boundaries."""

from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import AppError
from app.services.booking_rules import validate_booking_start

NOW = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
WINDOW = (datetime(2026, 10, 6, 9, 0, tzinfo=UTC), datetime(2026, 10, 6, 17, 0, tzinfo=UTC))
START = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)


def check(**overrides):
    args = dict(
        service_active=True,
        provider_active=True,
        provider_offers_service=True,
        start=START,
        windows_utc=[WINDOW],
        duration=timedelta(minutes=30),
        granularity=timedelta(minutes=15),
        now=NOW,
        lead_time=timedelta(minutes=60),
        horizon_days=60,
    )
    args.update(overrides)
    return validate_booking_start(**args)


def code_of(**overrides) -> str:
    with pytest.raises(AppError) as exc:
        check(**overrides)
    assert exc.value.status_code == 422
    return exc.value.code


def test_valid_start_passes():
    check()


def test_service_inactive():
    assert code_of(service_active=False) == "SERVICE_INACTIVE"


def test_provider_inactive():
    assert code_of(provider_active=False) == "PROVIDER_INACTIVE"


def test_provider_does_not_offer_service():
    assert code_of(provider_offers_service=False) == "PROVIDER_DOES_NOT_OFFER_SERVICE"


def test_start_in_past():
    assert code_of(start=NOW - timedelta(minutes=1)) == "START_IN_PAST"


def test_inside_lead_time():
    assert code_of(start=NOW + timedelta(minutes=59)) == "INSIDE_LEAD_TIME"


def test_exactly_at_lead_time_is_allowed():
    windows = [(NOW, NOW + timedelta(hours=4))]
    check(start=NOW + timedelta(minutes=60), windows_utc=windows)


def test_beyond_horizon():
    start = NOW + timedelta(days=60)
    assert code_of(start=start, windows_utc=[(start, start + timedelta(hours=2))]) == (
        "BEYOND_HORIZON"
    )


def test_last_instant_before_horizon_is_allowed():
    start = NOW + timedelta(days=60) - timedelta(minutes=15)
    check(start=start, windows_utc=[(start - timedelta(hours=1), start + timedelta(hours=2))])


def test_not_aligned():
    assert code_of(start=START + timedelta(minutes=10)) == "NOT_ALIGNED"


def test_outside_availability_before_opening():
    assert code_of(start=WINDOW[0] - timedelta(minutes=30)) == "OUTSIDE_AVAILABILITY"


def test_day_off_has_no_windows():
    assert code_of(windows_utc=[]) == "OUTSIDE_AVAILABILITY"


def test_ending_exactly_at_window_end_is_allowed():
    check(start=WINDOW[1] - timedelta(minutes=30))


def test_ending_after_window_end_is_outside():
    assert code_of(start=WINDOW[1] - timedelta(minutes=15)) == "OUTSIDE_AVAILABILITY"
