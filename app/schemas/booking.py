"""Request and response models for /bookings. Shape validation only.

The rules about *when* a booking may start live in `services/booking_rules.py`.
"""

import datetime as dt
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.booking import BookingStatus
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
    status: BookingStatus
    price_amount: int = Field(description="Whole UZS, as agreed when booked.")
    duration_minutes: int = Field(description="As agreed when booked.")
    notes: str | None
    cancel_reason: str | None
    created_at: dt.datetime

    model_config = ConfigDict(from_attributes=True)
