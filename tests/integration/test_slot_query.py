"""get_slots loads rules, exceptions and bookings and groups slots by provider (P5.2).

Frozen clock: 2026-10-01 07:00 UTC. 2026-10-05 is a Monday; Tashkent is UTC+5,
so 09:00 local is 04:00 UTC. Default settings: 15 min grid, 60 min lead time.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    AvailabilityException,
    AvailabilityRule,
    Booking,
    BookingStatus,
    Provider,
    ProviderService,
    Service,
    User,
)
from app.services.slot_query import get_slots

NOW = datetime(2026, 10, 1, 7, tzinfo=UTC)
MONDAY = date(2026, 10, 5)


def local(hour, minute=0) -> datetime:
    """A Tashkent wall-clock time on Monday 2026-10-05 as a UTC instant."""
    return datetime(2026, 10, 5, hour, minute, tzinfo=UTC) - timedelta(hours=5)


@pytest.fixture
def service(db: Session) -> Service:
    service = Service(name="Haircut", duration_minutes=30, price=60000)
    db.add(service)
    db.flush()
    return service


def make_provider(db, service, name="Jasur", hours=((9, 0), (10, 0)), offers=True) -> Provider:
    provider = Provider(name=name)
    db.add(provider)
    db.flush()
    if offers:
        db.add(ProviderService(provider_id=provider.id, service_id=service.id))
    if hours:
        db.add(
            AvailabilityRule(
                provider_id=provider.id,
                weekday=0,
                start_time=time(*hours[0]),
                end_time=time(*hours[1]),
            )
        )
    db.flush()
    return provider


def book(db, provider, service, start, status=BookingStatus.CONFIRMED, minutes=30) -> Booking:
    customer = db.query(User).first()
    if customer is None:
        customer = User(email="c@example.com", password_hash="x", full_name="C")
        db.add(customer)
        db.flush()
    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_id=service.id,
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        status=status,
        price_amount=service.price,
        duration_minutes=minutes,
    )
    db.add(booking)
    db.flush()
    return booking


def starts_of(result, index=0):
    return result.providers[index].starts


def test_slots_come_back_in_utc_on_the_settings_grid(db, service):
    make_provider(db, service)
    result = get_slots(db, service.id, MONDAY, None, NOW)
    assert result.timezone == "Asia/Tashkent"
    assert starts_of(result) == [local(9), local(9, 15), local(9, 30)]


def test_slots_shrink_after_a_booking(db, service):
    provider = make_provider(db, service)
    book(db, provider, service, local(9))
    # 09:00-09:30 is taken; 09:30 touches it and stays free
    assert starts_of(get_slots(db, service.id, MONDAY, None, NOW)) == [local(9, 30)]


def test_a_cancelled_booking_frees_its_slot(db, service):
    provider = make_provider(db, service)
    booking = book(db, provider, service, local(9))
    booking.status = BookingStatus.CANCELLED
    db.flush()
    assert local(9) in starts_of(get_slots(db, service.id, MONDAY, None, NOW))


def test_pending_bookings_block_and_completed_ones_do_not(db, service):
    provider = make_provider(db, service)
    book(db, provider, service, local(9), status=BookingStatus.PENDING)
    book(db, provider, service, local(9, 30), status=BookingStatus.COMPLETED)
    assert starts_of(get_slots(db, service.id, MONDAY, None, NOW)) == [local(9, 30)]


def test_another_providers_booking_does_not_matter(db, service):
    jasur = make_provider(db, service, "Jasur")
    aziz = make_provider(db, service, "Aziz")
    book(db, aziz, service, local(9))
    result = get_slots(db, service.id, MONDAY, None, NOW)
    by_name = {p.provider.name: p.starts for p in result.providers}
    assert by_name["Jasur"] == [local(9), local(9, 15), local(9, 30)]
    assert by_name["Aziz"] == [local(9, 30)]
    assert jasur.id != aziz.id


def test_no_provider_groups_every_active_provider_offering_the_service(db, service):
    make_provider(db, service, "Zafar")
    make_provider(db, service, "Aziz", hours=None)  # no hours: listed, no slots
    make_provider(db, service, "Off", offers=False)
    make_provider(db, service, "Gone").is_active = False
    db.flush()
    result = get_slots(db, service.id, MONDAY, None, NOW)
    assert [p.provider.name for p in result.providers] == ["Aziz", "Zafar"]
    assert starts_of(result, 0) == []


def test_a_provider_filter_returns_only_that_provider(db, service):
    make_provider(db, service, "Jasur")
    aziz = make_provider(db, service, "Aziz")
    result = get_slots(db, service.id, MONDAY, aziz.id, NOW)
    assert [p.provider.name for p in result.providers] == ["Aziz"]


def test_a_day_off_exception_removes_the_slots(db, service):
    provider = make_provider(db, service)
    db.add(AvailabilityException(provider_id=provider.id, date=MONDAY))
    db.flush()
    assert starts_of(get_slots(db, service.id, MONDAY, None, NOW)) == []


def test_a_booking_after_local_midnight_blocks_that_local_date(db, service):
    # 00:00-00:30 Tashkent Monday is Sunday 19:00 UTC; it must count as Monday's
    provider = make_provider(db, service, hours=((0, 0), (1, 0)))
    book(db, provider, service, local(0))
    assert starts_of(get_slots(db, service.id, MONDAY, None, NOW)) == [local(0, 30)]


def test_lead_time_and_horizon_come_from_the_business_settings(db, service):
    make_provider(db, service)
    now = local(9) - timedelta(minutes=30)  # lead time 60 -> earliest 09:30
    assert starts_of(get_slots(db, service.id, MONDAY, None, now)) == [local(9, 30)]
    horizon_now = local(9, 15) - timedelta(days=60)
    # horizon_end = now + 60 days = Monday 09:15 local: 09:00 stays, 09:15 is cut
    assert starts_of(get_slots(db, service.id, MONDAY, None, horizon_now)) == [local(9)]


def test_unknown_or_inactive_service_is_404(db, service):
    with pytest.raises(AppError) as unknown:
        get_slots(db, 9999, MONDAY, None, NOW)
    assert unknown.value.status_code == 404
    service.is_active = False
    db.flush()
    with pytest.raises(AppError) as inactive:
        get_slots(db, service.id, MONDAY, None, NOW)
    assert (inactive.value.status_code, inactive.value.code) == (404, "NOT_FOUND")


def test_unknown_or_inactive_provider_is_404(db, service):
    provider = make_provider(db, service)
    with pytest.raises(AppError) as unknown:
        get_slots(db, service.id, MONDAY, 9999, NOW)
    assert unknown.value.status_code == 404
    provider.is_active = False
    db.flush()
    with pytest.raises(AppError) as inactive:
        get_slots(db, service.id, MONDAY, provider.id, NOW)
    assert inactive.value.status_code == 404


def test_a_provider_who_does_not_offer_the_service_is_422(db, service):
    provider = make_provider(db, service, offers=False)
    with pytest.raises(AppError) as error:
        get_slots(db, service.id, MONDAY, provider.id, NOW)
    assert (error.value.status_code, error.value.code) == (
        422,
        "PROVIDER_DOES_NOT_OFFER_SERVICE",
    )
