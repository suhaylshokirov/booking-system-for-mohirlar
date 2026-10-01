"""create_booking: happy path, both overlap 409s, and the price snapshot (P6.2).

Frozen clock: 2026-10-01 07:00 UTC. 2026-10-05 is a Monday; Tashkent is UTC+5,
so 10:00 local is 05:00 UTC. Provider works 09:00-12:00 on Mondays.
"""

from datetime import UTC, datetime, time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    AvailabilityRule,
    Booking,
    BookingEvent,
    BookingStatus,
    Provider,
    ProviderService,
    Service,
    User,
)
from app.services.booking import create_booking

NOW = datetime(2026, 10, 1, 7, tzinfo=UTC)
TEN = datetime(2026, 10, 5, 5, 0, tzinfo=UTC)  # 10:00 Tashkent
TEN_THIRTY = datetime(2026, 10, 5, 5, 30, tzinfo=UTC)
TEN_FIFTEEN = datetime(2026, 10, 5, 5, 15, tzinfo=UTC)


@pytest.fixture
def service(db: Session) -> Service:
    service = Service(name="Haircut", duration_minutes=30, price=60000)
    db.add(service)
    db.flush()
    return service


def make_provider(db: Session, service: Service, name: str = "Jasur") -> Provider:
    provider = Provider(name=name)
    db.add(provider)
    db.flush()
    db.add(ProviderService(provider_id=provider.id, service_id=service.id))
    db.add(
        AvailabilityRule(provider_id=provider.id, weekday=0, start_time=time(9), end_time=time(12))
    )
    db.flush()
    return provider


def make_user(db: Session, email: str) -> User:
    user = User(email=email, full_name=email)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def provider(db: Session, service: Service) -> Provider:
    return make_provider(db, service)


@pytest.fixture
def ali(db: Session) -> User:
    return make_user(db, "ali@example.com")


def book(db, user, service, provider, start, notes=None) -> Booking:
    return create_booking(db, user, service.id, provider.id, start, notes, NOW)


def test_happy_path_creates_pending_booking_and_creation_event(db, ali, service, provider):
    booking = book(db, ali, service, provider, TEN, "short back and sides")

    assert booking.status == BookingStatus.PENDING
    assert booking.start_at == TEN
    assert booking.end_at == TEN_THIRTY
    assert booking.price_amount == 60000
    assert booking.duration_minutes == 30
    assert booking.notes == "short back and sides"
    events = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == booking.id)).all()
    assert len(events) == 1
    assert events[0].from_status is None
    assert events[0].to_status == BookingStatus.PENDING
    assert events[0].actor_id == ali.id


def test_same_provider_overlap_is_409_slot_taken(db, ali, service, provider):
    book(db, ali, service, provider, TEN)
    bob = make_user(db, "bob@example.com")

    with pytest.raises(AppError) as exc:
        book(db, bob, service, provider, TEN_FIFTEEN)

    assert exc.value.status_code == 409
    assert exc.value.code == "SLOT_TAKEN"


def test_customer_overlap_with_another_provider_is_409_customer_overlap(db, ali, service, provider):
    book(db, ali, service, provider, TEN)
    other = make_provider(db, service, "Aziz")

    with pytest.raises(AppError) as exc:
        book(db, ali, service, other, TEN_FIFTEEN)

    assert exc.value.status_code == 409
    assert exc.value.code == "CUSTOMER_OVERLAP"


def test_back_to_back_bookings_are_allowed(db, ali, service, provider):
    book(db, ali, service, provider, TEN)
    second = book(db, ali, service, provider, TEN_THIRTY)
    assert second.start_at == TEN_THIRTY


def test_cancelled_booking_frees_the_slot(db, ali, service, provider):
    first = book(db, ali, service, provider, TEN)
    first.status = BookingStatus.CANCELLED
    db.flush()
    bob = make_user(db, "bob@example.com")

    assert book(db, bob, service, provider, TEN).status == BookingStatus.PENDING


def test_snapshot_survives_a_later_price_and_duration_change(db, ali, service, provider):
    booking = book(db, ali, service, provider, TEN)

    service.price = 90000
    service.duration_minutes = 45
    db.flush()
    db.refresh(booking)

    assert booking.price_amount == 60000
    assert booking.duration_minutes == 30
    assert booking.end_at == TEN_THIRTY


def test_validation_rule_is_applied(db, ali, service, provider):
    with pytest.raises(AppError) as exc:
        book(db, ali, service, provider, TEN_FIFTEEN.replace(minute=7))
    assert exc.value.code == "NOT_ALIGNED"


def test_unknown_service_or_provider_is_404(db, ali, service, provider):
    with pytest.raises(AppError) as exc:
        create_booking(db, ali, 99999, provider.id, TEN, None, NOW)
    assert exc.value.status_code == 404
    with pytest.raises(AppError) as exc:
        create_booking(db, ali, service.id, 99999, TEN, None, NOW)
    assert exc.value.status_code == 404


def test_database_constraint_maps_to_409_when_the_precheck_is_skipped(
    db, ali, service, provider, monkeypatch
):
    """The race path: the pre-check sees nothing, so only the constraint can stop the insert."""
    book(db, ali, service, provider, TEN)
    monkeypatch.setattr("app.services.booking._precheck_overlap", lambda *args: None)
    bob = make_user(db, "bob@example.com")

    with pytest.raises(AppError) as exc:
        book(db, bob, service, provider, TEN)
    assert exc.value.code == "SLOT_TAKEN"

    other = make_provider(db, service, "Aziz")
    with pytest.raises(AppError) as exc:
        book(db, ali, service, other, TEN)
    assert exc.value.code == "CUSTOMER_OVERLAP"
    # The session is still usable after both rejected inserts.
    assert db.scalar(select(Booking.id).limit(1)) is not None


def test_a_deadlock_between_overlapping_inserts_is_409_not_500(
    db, ali, service, provider, monkeypatch
):
    from psycopg import errors as pg_errors
    from sqlalchemy.exc import OperationalError

    real_flush = db.flush

    def flush_that_deadlocks_on_the_booking_insert(*args, **kwargs):
        if any(isinstance(obj, Booking) for obj in db.new):
            raise OperationalError("INSERT ...", {}, pg_errors.DeadlockDetected())
        return real_flush(*args, **kwargs)

    monkeypatch.setattr(db, "flush", flush_that_deadlocks_on_the_booking_insert)

    with pytest.raises(AppError) as exc:
        book(db, ali, service, provider, TEN)

    assert exc.value.status_code == 409
    assert exc.value.code == "SLOT_TAKEN"
