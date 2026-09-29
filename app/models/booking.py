"""`bookings` (an appointment) and `booking_events` (its audit trail).

Rules stored here:

* `[start_at, end_at)` is a half-open range of instants (`timestamptz`, UTC),
  and `end_at` is after `start_at`.
* `price_amount` and `duration_minutes` are **snapshots** copied from the
  service when the booking is made, so editing the service later never changes
  what the customer agreed to (ADR 0007).
* `cancelled_by_id` / `cancel_reason` only exist on a cancelled booking.
* Customers, providers and services are referenced with `ON DELETE RESTRICT`:
  they are deactivated, never deleted, so history survives.

Double booking is prevented by two exclusion constraints on this table,
`no_provider_overlap` and `no_customer_overlap`. They are created in a
migration, not here; see docs/database.md.
"""

import enum
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BookingStatus(enum.StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    COMPLETED = "completed"


# One Postgres enum type shared by bookings.status and both status columns of
# booking_events. The migration creates the type once (`create_type=False` on
# the columns), otherwise the second table would try to create it again.
booking_status_type = Enum(
    BookingStatus,
    name="booking_status",
    values_callable=lambda e: [m.value for m in e],
    create_type=False,
)


class Booking(TimestampMixin, Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="end_after_start"),
        CheckConstraint("price_amount >= 0", name="price_not_negative"),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        # Cancellation details on a booking that is not cancelled would be a
        # lie about its history.
        CheckConstraint(
            "status = 'cancelled' OR (cancelled_by_id IS NULL AND cancel_reason IS NULL)",
            name="cancellation_fields_only_when_cancelled",
        ),
        # "My bookings" and "provider's day" are the two hot queries, plus the
        # admin filter by status.
        Index("ix_bookings_customer_start", "customer_id", "start_at"),
        Index("ix_bookings_provider_start", "provider_id", "start_at"),
        Index("ix_bookings_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="RESTRICT"))
    service_id: Mapped[int] = mapped_column(ForeignKey("services.id", ondelete="RESTRICT"))
    start_at: Mapped[datetime]
    end_at: Mapped[datetime]
    status: Mapped[BookingStatus] = mapped_column(
        booking_status_type, server_default=BookingStatus.PENDING.value
    )
    # Snapshots of the service at booking time (ADR 0007).
    price_amount: Mapped[int]
    duration_minutes: Mapped[int]
    notes: Mapped[str | None] = mapped_column(String(500))
    cancelled_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    cancel_reason: Mapped[str | None] = mapped_column(String(500))


class BookingEvent(Base):
    """One row per status change. Append-only: rows are never updated or deleted.

    `from_status` is NULL for the creation event. `actor_id` is NULL when the
    system acted (for example, expiring a stale pending booking). Events written
    in one transaction share `created_at` (the database's `now()` is the
    transaction start), so order ties are broken by `id`.
    """

    __tablename__ = "booking_events"
    __table_args__ = (Index("ix_booking_events_booking_created", "booking_id", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id", ondelete="RESTRICT"))
    from_status: Mapped[BookingStatus | None] = mapped_column(booking_status_type)
    to_status: Mapped[BookingStatus] = mapped_column(booking_status_type)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reason: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
