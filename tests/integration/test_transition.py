"""booking.transition: guarded update, events, and cancellation details (P7.2).

Frozen clock: 2026-10-01 07:00 UTC; the booking starts 2026-10-05 05:00 UTC.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Booking, BookingEvent, BookingStatus, Provider, Service, User, UserRole
from app.services import booking as booking_service
from app.services.booking import transition
from tests.integration.test_create_booking import book, make_provider, make_user

NOW = datetime(2026, 10, 1, 7, tzinfo=UTC)
TEN = datetime(2026, 10, 5, 5, 0, tzinfo=UTC)


@pytest.fixture
def service(db: Session) -> Service:
    service = Service(name="Haircut", duration_minutes=30, price=60000)
    db.add(service)
    db.flush()
    return service


@pytest.fixture
def provider(db: Session, service: Service) -> Provider:
    return make_provider(db, service)


@pytest.fixture
def ali(db: Session) -> User:
    return make_user(db, "ali@example.com")


@pytest.fixture
def admin_user(db: Session) -> User:
    user = make_user(db, "boss@example.com")
    user.role = UserRole.ADMIN
    db.flush()
    return user


@pytest.fixture
def pending(db, ali, service, provider) -> Booking:
    return book(db, ali, service, provider, TEN)


def events(db: Session, booking: Booking) -> list[BookingEvent]:
    return list(
        db.scalars(
            select(BookingEvent)
            .where(BookingEvent.booking_id == booking.id)
            .order_by(BookingEvent.id)
        )
    )


def test_confirm_updates_status_and_writes_an_event(db, admin_user, pending):
    booking = transition(db, admin_user, pending.id, BookingStatus.CONFIRMED, NOW)

    assert booking.status == BookingStatus.CONFIRMED
    last = events(db, booking)[-1]
    assert (last.from_status, last.to_status) == (BookingStatus.PENDING, BookingStatus.CONFIRMED)
    assert last.actor_id == admin_user.id


def test_cancel_records_who_and_why(db, ali, pending):
    booking = transition(db, ali, pending.id, BookingStatus.CANCELLED, NOW, "changed my mind")

    assert booking.status == BookingStatus.CANCELLED
    assert booking.cancelled_by_id == ali.id
    assert booking.cancel_reason == "changed my mind"
    assert events(db, booking)[-1].reason == "changed my mind"


def test_stale_expected_status_is_409_and_writes_no_event(db, admin_user, pending, monkeypatch):
    real_check = booking_service.check_transition

    def check_then_lose_the_race(*args, **kwargs):
        real_check(*args, **kwargs)
        # Another request commits a cancel after our read and rules check.
        db.execute(
            text("UPDATE bookings SET status = 'cancelled' WHERE id = :i"), {"i": pending.id}
        )

    monkeypatch.setattr(booking_service, "check_transition", check_then_lose_the_race)
    before = len(events(db, pending))

    with pytest.raises(AppError) as exc:
        transition(db, admin_user, pending.id, BookingStatus.CONFIRMED, NOW)

    assert exc.value.status_code == 409
    assert exc.value.code == "BOOKING_STATE_CHANGED"
    assert len(events(db, pending)) == before
    # A page rendered after the failure must show what is really in the database.
    assert pending.status == BookingStatus.CANCELLED


def test_illegal_transition_changes_nothing(db, admin_user, pending):
    with pytest.raises(AppError) as exc:
        transition(db, admin_user, pending.id, BookingStatus.COMPLETED, NOW)

    assert exc.value.code == "INVALID_TRANSITION"
    db.refresh(pending)
    assert pending.status == BookingStatus.PENDING
    assert len(events(db, pending)) == 1


def test_someone_elses_booking_is_404(db, pending):
    bob = make_user(db, "bob@example.com")

    with pytest.raises(AppError) as exc:
        transition(db, bob, pending.id, BookingStatus.CANCELLED, NOW)

    assert (exc.value.status_code, exc.value.code) == (404, "BOOKING_NOT_FOUND")


def test_cancelling_frees_the_slot_for_another_customer(db, ali, pending, service, provider):
    transition(db, ali, pending.id, BookingStatus.CANCELLED, NOW)
    bob = make_user(db, "bob@example.com")

    other = book(db, bob, service, provider, TEN)

    assert other.status == BookingStatus.PENDING
    assert other.start_at == TEN + timedelta(0)
