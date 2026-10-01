"""Request and response models for /bookings. Shape validation only.

The rules about *when* a booking may start live in `services/booking_rules.py`.
"""

import datetime as dt
from typing import Annotated, Any, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.core.timezones import utc_to_local
from app.models.booking import BookingStatus
from app.models.user import UserRole
from app.schemas.types import UtcDatetime

_EXAMPLE = {
    "service_id": 1,
    "provider_id": 1,
    "start_at": "2026-10-05T04:00:00Z",
    "notes": "Short back and sides, please.",
}


class BookingCreate(BaseModel):
    service_id: int
    provider_id: int
    # Must carry an offset ("Z" or "+05:00"); a naive time is a 422 (edge case 12).
    start_at: UtcDatetime
    notes: Annotated[str, StringConstraints(max_length=500)] | None = None

    model_config = ConfigDict(str_strip_whitespace=True, json_schema_extra={"examples": [_EXAMPLE]})

    @field_validator("notes")
    @classmethod
    def _blank_notes_to_none(cls, value: str | None) -> str | None:
        return value or None


class CancelRequest(BaseModel):
    """Optional for a customer or for cancelling a pending booking; an admin
    cancelling a confirmed booking must give one (`REASON_REQUIRED`)."""

    reason: Annotated[str, StringConstraints(max_length=500)] | None = None

    model_config = ConfigDict(
        str_strip_whitespace=True, json_schema_extra={"examples": [{"reason": "Feeling unwell."}]}
    )

    @field_validator("reason")
    @classmethod
    def _blank_reason_to_none(cls, value: str | None) -> str | None:
        return value or None


class BookingResponse(BaseModel):
    id: int
    customer_id: int
    provider_id: int
    service_id: int
    start_at: dt.datetime = Field(description="UTC instant.")
    end_at: dt.datetime = Field(description="UTC instant, exclusive.")
    local_start: dt.datetime = Field(
        description="`start_at` on the business's clock, with its UTC offset "
        "(`2026-10-05T09:00:00+05:00`). The same instant, for display."
    )
    local_end: dt.datetime = Field(description="`end_at` on the business's clock, with its offset.")
    timezone: str = Field(description="IANA name of the business timezone, e.g. `Asia/Tashkent`.")
    status: BookingStatus
    price_amount: int = Field(description="Whole UZS, as agreed when booked.")
    duration_minutes: int = Field(description="As agreed when booked.")
    notes: str | None
    cancel_reason: str | None
    created_at: dt.datetime

    @classmethod
    def from_booking(cls, booking: Any, timezone: str, **extra: Any) -> Self:
        """Build the response from a `Booking`, adding the local times.

        The database holds UTC only (rule 4); the local fields are derived here
        with `utc_to_local`, the one conversion function, so a client never has
        to do timezone arithmetic of its own.
        """
        data = {
            name: getattr(booking, name)
            for name in cls.model_fields
            if name not in ("local_start", "local_end", "timezone") and name not in extra
        }
        return cls(
            **data,
            **extra,
            local_start=utc_to_local(booking.start_at, timezone),
            local_end=utc_to_local(booking.end_at, timezone),
            timezone=timezone,
        )


class EventActor(BaseModel):
    id: int
    role: UserRole
    name: str


class BookingEventResponse(BaseModel):
    from_status: BookingStatus | None = Field(description="`null` for the creation event.")
    to_status: BookingStatus
    actor: EventActor | None = Field(description="`null` when the system acted.")
    reason: str | None
    created_at: dt.datetime


class AdminBookingResponse(BookingResponse):
    stale_pending: bool = Field(
        description="Still `pending` although its start has passed. Cancel it "
        "(`POST /bookings/{id}/cancel`); it can no longer be confirmed."
    )
