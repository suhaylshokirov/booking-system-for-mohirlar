"""Notifications are written in the booking's transaction (P10.2, ADR 0009).

Frozen clock: Thursday 2026-10-01 07:00 UTC. Jasur works Friday 2026-10-02
09:00-12:00 local (Tashkent, UTC+5), i.e. 04:00-07:00 UTC.
"""

import logging
from datetime import UTC, datetime, time

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import (
    AvailabilityRule,
    BookingStatus,
    OutboxMessage,
    Provider,
    ProviderService,
    Service,
)
from app.models.user import User, UserRole
from app.services import notifications
from app.services.booking import create_booking, transition

NOW = datetime(2026, 10, 1, 7, tzinfo=UTC)
NINE = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)  # 09:00 Tashkent


def _user(db: Session, email: str, role=UserRole.CUSTOMER) -> User:
    user = User(email=email, password_hash="x", full_name=email.split("@")[0], role=role)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def jasur(db) -> Provider:
    service = Service(name="Haircut", duration_minutes=30, price=60_000)
    provider = Provider(name="Jasur")
    db.add_all([service, provider])
    db.flush()
    db.add(ProviderService(provider_id=provider.id, service_id=service.id))
    db.add(
        AvailabilityRule(provider_id=provider.id, weekday=4, start_time=time(9), end_time=time(12))
    )
    db.flush()
    return provider


@pytest.fixture
def aziza(db) -> User:
    return _user(db, "aziza@example.com")


@pytest.fixture
def staff(db) -> User:
    return _user(db, "staff@example.com", UserRole.ADMIN)


def _book(db, customer, jasur, start=NINE):
    service = db.scalar(select(Service))
    return create_booking(db, customer, service.id, jasur.id, start, None, NOW)


def _outbox(db) -> list[OutboxMessage]:
    return list(db.scalars(select(OutboxMessage).order_by(OutboxMessage.id)))


def test_creating_a_booking_queues_a_message_for_the_customer(db, jasur, aziza):
    booking = _book(db, aziza, jasur)

    (message,) = _outbox(db)
    assert message.event == "booking_created"
    assert message.booking_id == booking.id
    assert message.recipient_user_id == aziza.id
    assert message.recipient_email == "aziza@example.com"
    assert "Fri 02 Oct 2026, 09:00 (Asia/Tashkent)" in message.body
    assert message.sent_at is None


def test_confirming_queues_a_message(db, jasur, aziza, staff):
    booking = _book(db, aziza, jasur)

    transition(db, staff, booking.id, BookingStatus.CONFIRMED, NOW)

    assert [m.event for m in _outbox(db)] == ["booking_created", "booking_confirmed"]


def test_cancelling_queues_a_message_that_says_who_and_why(db, jasur, aziza, staff):
    booking = _book(db, aziza, jasur)
    transition(db, staff, booking.id, BookingStatus.CONFIRMED, NOW)

    transition(db, staff, booking.id, BookingStatus.CANCELLED, NOW, "Barber is ill")

    last = _outbox(db)[-1]
    assert last.event == "booking_cancelled"
    assert "cancelled by the business" in last.body
    assert "Reason: Barber is ill" in last.body


def test_a_customer_cancelling_is_told_it_was_by_them(db, jasur, aziza):
    booking = _book(db, aziza, jasur)

    transition(db, aziza, booking.id, BookingStatus.CANCELLED, NOW)

    assert "cancelled by you" in _outbox(db)[-1].body


def test_completing_sends_nothing(db, jasur, aziza, staff):
    booking = _book(db, aziza, jasur)
    transition(db, staff, booking.id, BookingStatus.CONFIRMED, NOW)
    before = len(_outbox(db))

    after_it_ends = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
    transition(db, staff, booking.id, BookingStatus.COMPLETED, after_it_ends)

    assert len(_outbox(db)) == before


def test_a_refused_booking_queues_nothing(db, jasur, aziza):
    _book(db, aziza, jasur)
    bob = _user(db, "bob@example.com")

    with pytest.raises(AppError) as error:
        _book(db, bob, jasur)  # the same slot

    assert error.value.code == "SLOT_TAKEN"
    assert [m.recipient_user_id for m in _outbox(db)] == [aziza.id]


def test_a_rolled_back_booking_takes_its_message_with_it(db, jasur, aziza):
    """Same transaction: undo the booking and the message is undone too."""
    savepoint = db.begin_nested()
    _book(db, aziza, jasur)
    assert len(_outbox(db)) == 1

    savepoint.rollback()

    assert db.scalar(select(func.count()).select_from(OutboxMessage)) == 0


def test_the_console_notifier_logs_what_is_sent(db, jasur, aziza, caplog):
    with caplog.at_level(logging.INFO, logger="navbat.notifications"):
        _book(db, aziza, jasur)

    assert "booking_created" in caplog.text
    assert "aziza@example.com" in caplog.text


def test_notifiers_are_pluggable(db, jasur, aziza, monkeypatch):
    class Recorder:
        def __init__(self):
            self.sent = []

        def send(self, db, message):
            self.sent.append(message)

    recorder = Recorder()
    monkeypatch.setattr(notifications, "NOTIFIERS", [recorder])

    _book(db, aziza, jasur)

    assert [m.event for m in recorder.sent] == [notifications.NotificationEvent.BOOKING_CREATED]
    assert _outbox(db) == []


def test_the_message_keeps_the_address_it_was_sent_to(db, jasur, aziza):
    """A snapshot: changing the user's email later does not rewrite history."""
    _book(db, aziza, jasur)

    aziza.email = "new@example.com"
    db.flush()

    assert _outbox(db)[0].recipient_email == "aziza@example.com"
