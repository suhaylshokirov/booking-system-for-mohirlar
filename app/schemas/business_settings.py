"""Request and response models for /settings. Shape validation only.

Whether the timezone exists and whether a new granularity fits the existing
services are business rules and live in `services/business_settings.py`.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# The slot grid sizes offered to barbers: each divides an hour evenly, so
# slots line up with the clock face.
SlotGranularity = Literal[5, 10, 15, 20, 30, 60]

_EXAMPLE = {
    "name": "Barbershop Navbat",
    "timezone": "Asia/Tashkent",
    "currency": "UZS",
    "slot_granularity_minutes": 15,
    "min_lead_time_minutes": 60,
    "max_booking_horizon_days": 60,
    "cancellation_cutoff_hours": 2,
}


class SettingsResponse(BaseModel):
    """Everything a customer or the barber UI needs to know about the business.

    Nothing here is secret (no id, no internal flags): the horizon and cutoff
    are shown to customers so a refusal is never a surprise.
    """

    name: str
    timezone: str = Field(description="IANA name. Availability is wall-clock time in this zone.")
    currency: str = Field(description="ISO 4217 code. Prices are whole units of it.")
    slot_granularity_minutes: int = Field(description="Slots start on multiples of this.")
    min_lead_time_minutes: int = Field(description="How far ahead a booking must be made.")
    max_booking_horizon_days: int = Field(description="How far ahead a booking may be made.")
    cancellation_cutoff_hours: int = Field(
        description="Customers cannot cancel closer to the start than this."
    )
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{**_EXAMPLE, "updated_at": "2026-10-01T07:00:00Z"}]},
    )


class SettingsUpdate(BaseModel):
    """A partial update: send only the fields to change.

    Omitted fields keep their value. `null` is refused, because every setting
    always has a value.
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    slot_granularity_minutes: SlotGranularity | None = None
    min_lead_time_minutes: int | None = Field(default=None, ge=0, le=10080)
    max_booking_horizon_days: int | None = Field(default=None, ge=1, le=365)
    cancellation_cutoff_hours: int | None = Field(default=None, ge=0, le=720)

    @model_validator(mode="after")
    def _only_real_values(self) -> "SettingsUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one setting to change")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null; omit it to leave it unchanged")
        return self

    # Strips before the length checks, so a name of only spaces is refused.
    model_config = ConfigDict(
        str_strip_whitespace=True, json_schema_extra={"examples": [{"timezone": "Asia/Tashkent"}]}
    )
