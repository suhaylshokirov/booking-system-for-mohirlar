"""The notification text and the notifier plumbing that need no database (P10.2)."""

import logging
from datetime import UTC, datetime

from app.models import Booking, BookingStatus, BusinessSettings, User
from app.services.notifications import (
    ConsoleNotifier,
    Message,
    NotificationEvent,
    compose_message,
)

START = datetime(2026, 10, 5, 5, 0, tzinfo=UTC)  # 10:00 in Tashkent


def parts(cancel_reason=None):
    booking = Booking(
        id=7,
        customer_id=3,
        start_at=START,
        status=BookingStatus.PENDING,
        cancel_reason=cancel_reason,
    )
    customer = User(id=3, email="ali@example.com", full_name="Ali")
    business = BusinessSettings(name="Navbat Barbers", timezone="Asia/Tashkent")
    return booking, customer, business


def compose(event, cancelled_by=None, cancel_reason=None):
    booking, customer, business = parts(cancel_reason)
    return compose_message(
        event, booking, customer, "Haircut", "Jasur", business, cancelled_by=cancelled_by
    )


def test_created_message_names_the_local_time_and_the_zone():
    message = compose(NotificationEvent.BOOKING_CREATED)

    assert message.recipient_email == "ali@example.com"
    assert message.subject == "Navbat Barbers: booking requested"
    assert "Haircut with Jasur, Mon 05 Oct 2026, 10:00 (Asia/Tashkent)" in message.body
    assert message.body.startswith("Hello Ali,")


def test_confirmed_message():
    message = compose(NotificationEvent.BOOKING_CONFIRMED)

    assert message.subject == "Navbat Barbers: booking confirmed"
    assert "Your booking is confirmed" in message.body


def test_cancel_by_the_customer_says_by_you():
    ali = User(id=3, email="ali@example.com", full_name="Ali")

    assert "cancelled by you" in compose(NotificationEvent.BOOKING_CANCELLED, ali).body


def test_cancel_by_staff_says_by_the_business_and_gives_the_reason():
    staff = User(id=1, email="staff@example.com", full_name="Staff")

    body = compose(NotificationEvent.BOOKING_CANCELLED, staff, "Barber is ill").body

    assert "cancelled by the business" in body
    assert "Reason: Barber is ill" in body


def test_console_notifier_logs_the_message(caplog):
    message = Message(NotificationEvent.BOOKING_CREATED, 7, 3, "ali@example.com", "Subject", "Body")

    with caplog.at_level(logging.INFO, logger="navbat.notifications"):
        ConsoleNotifier().send(None, message)

    assert "booking_created" in caplog.text
    assert "ali@example.com" in caplog.text
    assert "Subject" in caplog.text
