"""Telling the customer what happened to their booking.

`notify_booking` is called by `booking.create_booking` and `booking.transition`
after the change is written. It writes the message through every notifier in
`NOTIFIERS`:

* `OutboxNotifier` inserts an `outbox_messages` row **in the caller's
  transaction**. If the booking is rolled back (a lost race, a failed commit),
  the message goes with it, so nobody is told about a booking that does not
  exist. If it commits, the message is durable even if the process dies right
  after. A delivery worker would pick unsent rows up later (ADR 0009).
* `ConsoleNotifier` logs the message. It is the development view of what would
  be sent. It runs inside the transaction too, so unlike the outbox it can log
  a message for a booking that is later rolled back; it is not a record.

No SMTP dependency: a real mail sender would be one more `Notifier`, or a
worker reading the outbox.

Who is told: the customer, on create (request received), confirm and cancel.
There is no business email in the settings, so the business is not notified;
the admin sees new bookings on the dashboard.
"""

import enum
import logging
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session

from app.core.timezones import utc_to_local
from app.models.booking import Booking
from app.models.business_settings import BusinessSettings
from app.models.outbox import OutboxMessage
from app.models.provider import Provider
from app.models.service import Service
from app.models.user import User
from app.services.business_settings import get_business_settings

logger = logging.getLogger("navbat.notifications")


class NotificationEvent(enum.StrEnum):
    BOOKING_CREATED = "booking_created"
    BOOKING_CONFIRMED = "booking_confirmed"
    BOOKING_CANCELLED = "booking_cancelled"


@dataclass(frozen=True)
class Message:
    event: NotificationEvent
    booking_id: int
    recipient_user_id: int
    recipient_email: str
    subject: str
    body: str


class Notifier(Protocol):
    def send(self, db: Session, message: Message) -> None:
        """Deliver or queue `message`. Runs inside the caller's transaction."""


class ConsoleNotifier:
    def send(self, db: Session, message: Message) -> None:
        logger.info(
            "notification %s to %s: %s\n%s",
            message.event.value,
            message.recipient_email,
            message.subject,
            message.body,
        )


class OutboxNotifier:
    def send(self, db: Session, message: Message) -> None:
        # Only added to the session: the request's commit writes it together
        # with the booking. Never commit here.
        db.add(
            OutboxMessage(
                event=message.event.value,
                booking_id=message.booking_id,
                recipient_user_id=message.recipient_user_id,
                recipient_email=message.recipient_email,
                subject=message.subject,
                body=message.body,
            )
        )
        db.flush()


# Tests replace this to check what gets sent, or to fail a notifier.
NOTIFIERS: list[Notifier] = [OutboxNotifier(), ConsoleNotifier()]


def compose_message(
    event: NotificationEvent,
    booking: Booking,
    customer: User,
    service_name: str,
    provider_name: str,
    business: BusinessSettings,
    cancelled_by: User | None = None,
) -> Message:
    """Pure: the subject and plain-text body for one event.

    Times are the business's local time with the zone named, so the customer
    never has to guess which clock it is.
    """
    start = utc_to_local(booking.start_at, business.timezone)
    when = f"{start:%a %d %b %Y, %H:%M} ({business.timezone})"
    what = f"{service_name} with {provider_name}, {when}"

    match event:
        case NotificationEvent.BOOKING_CREATED:
            subject = f"{business.name}: booking requested"
            lines = [f"We received your booking: {what}.", "We will confirm it soon."]
        case NotificationEvent.BOOKING_CONFIRMED:
            subject = f"{business.name}: booking confirmed"
            lines = [f"Your booking is confirmed: {what}."]
        case NotificationEvent.BOOKING_CANCELLED:
            subject = f"{business.name}: booking cancelled"
            by_you = cancelled_by is not None and cancelled_by.id == customer.id
            lines = [
                f"Your booking was cancelled{' by you' if by_you else ' by the business'}: {what}."
            ]
            if booking.cancel_reason:
                lines.append(f"Reason: {booking.cancel_reason}")
    body = f"Hello {customer.full_name},\n\n" + "\n".join(lines) + f"\n\n{business.name}"
    return Message(event, booking.id, customer.id, customer.email, subject, body)


def notify_booking(
    db: Session, event: NotificationEvent, booking: Booking, actor: User | None = None
) -> None:
    """Tell the booking's customer about `event` through every notifier.

    Call it after the booking change is flushed and in the same transaction.
    `actor` is who caused a cancellation, so the text can say "by you" or "by
    the business". An exception from a notifier propagates and rolls the whole
    request back: a booking whose announcement cannot be recorded is not made.
    """
    customer = db.get(User, booking.customer_id)
    service = db.get(Service, booking.service_id)
    provider = db.get(Provider, booking.provider_id)
    message = compose_message(
        event,
        booking,
        customer,
        service.name,
        provider.name,
        get_business_settings(db),
        cancelled_by=actor,
    )
    for notifier in NOTIFIERS:
        notifier.send(db, message)
