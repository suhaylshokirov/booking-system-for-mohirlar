"""Request and response models for weekly availability rules. Shape validation only.

Whether a time fits the slot grid and whether a rule overlaps another are
business rules and live in `services/availability.py`.
"""

from datetime import date as Date
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.schemas.types import LocalTime

_EXAMPLE = {"weekday": 0, "start_time": "09:00", "end_time": "18:00"}


class RuleCreate(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0 = Monday ... 6 = Sunday.")
    start_time: LocalTime = Field(description="Local time in the business timezone.")
    end_time: LocalTime = Field(description="Local time; must be later than `start_time`.")

    model_config = ConfigDict(json_schema_extra={"examples": [_EXAMPLE]})

    @model_validator(mode="after")
    def _ends_after_it_starts(self) -> "RuleCreate":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        return self


class RuleUpdate(BaseModel):
    """A partial update: send only the fields to change.

    The result (the rule with these changes applied) is checked as a whole, so
    moving only `end_time` earlier than the stored `start_time` is refused.
    """

    weekday: int | None = Field(default=None, ge=0, le=6)
    start_time: LocalTime | None = None
    end_time: LocalTime | None = None

    model_config = ConfigDict(json_schema_extra={"examples": [{"end_time": "19:00"}]})

    @model_validator(mode="after")
    def _only_real_values(self) -> "RuleUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null; omit it to leave it unchanged")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class RuleResponse(BaseModel):
    id: int
    provider_id: int
    weekday: int = Field(description="0 = Monday ... 6 = Sunday.")
    start_time: LocalTime
    end_time: LocalTime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{"id": 1, "provider_id": 1, **_EXAMPLE}]},
    )


_EXCEPTION_DAY_OFF = {"date": "2026-10-12", "reason": "Public holiday"}
_EXCEPTION_HOURS = {"date": "2026-10-13", "start_time": "12:00", "end_time": "16:00"}


def _blank_to_none(value: str | None) -> str | None:
    return value.strip() or None if value is not None else None


class ExceptionCreate(BaseModel):
    """One date that replaces the provider's weekly rules.

    No times means a day off; both times mean "open only in this window".
    """

    date: Date = Field(description="Local date in the business timezone; today or later.")
    start_time: LocalTime | None = Field(default=None, description="Omit both times for a day off.")
    end_time: LocalTime | None = None
    reason: str | None = Field(default=None, max_length=200)

    model_config = ConfigDict(
        json_schema_extra={"examples": [_EXCEPTION_DAY_OFF, _EXCEPTION_HOURS]}
    )

    _blank_reason = field_validator("reason")(_blank_to_none)

    @model_validator(mode="after")
    def _day_off_or_a_window(self) -> "ExceptionCreate":
        if (self.start_time is None) != (self.end_time is None):
            raise ValueError("send both start_time and end_time, or neither for a day off")
        if self.start_time is not None and self.end_time <= self.start_time:
            raise ValueError("end_time must be later than start_time")
        return self


class ExceptionUpdate(BaseModel):
    """A partial update: send only the fields to change.

    Unlike everywhere else, `null` is meaningful here: `{"start_time": null,
    "end_time": null}` turns the date into a day off, and `reason: null` clears
    the reason. `date` cannot be null. The result is checked as a whole.
    """

    date: Date | None = None
    start_time: LocalTime | None = None
    end_time: LocalTime | None = None
    reason: str | None = Field(default=None, max_length=200)

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"start_time": None, "end_time": None}]}
    )

    _blank_reason = field_validator("reason")(_blank_to_none)

    @model_validator(mode="after")
    def _only_real_values(self) -> "ExceptionUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        if "date" in self.model_fields_set and self.date is None:
            raise ValueError("date cannot be null; omit it to leave it unchanged")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_unset=True)


class ExceptionResponse(BaseModel):
    id: int
    provider_id: int
    date: Date
    start_time: LocalTime | None
    end_time: LocalTime | None
    reason: str | None

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={"examples": [{"id": 1, "provider_id": 1, **_EXCEPTION_DAY_OFF}]},
    )

    @computed_field(description="True when the provider does not work at all that date.")
    @property
    def is_day_off(self) -> bool:
        return self.start_time is None


class ConflictResponse(BaseModel):
    """A future booking that no longer fits the provider's hours."""

    booking_id: int
    status: Literal["pending", "confirmed"]
    start_at: datetime
    end_at: datetime
    customer_id: int
    service_id: int
    reason: Literal["day_off", "no_hours", "outside_hours"] = Field(
        description="`day_off`: an exception closes that date; `no_hours`: no weekly rule "
        "covers that weekday; `outside_hours`: there are hours that day, but not around "
        "the booking."
    )

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "booking_id": 12,
                    "status": "confirmed",
                    "start_at": "2026-10-05T11:00:00Z",
                    "end_at": "2026-10-05T11:30:00Z",
                    "customer_id": 3,
                    "service_id": 1,
                    "reason": "outside_hours",
                }
            ]
        }
    )

    @classmethod
    def from_conflict(cls, conflict: Any) -> "ConflictResponse":
        booking = conflict.booking
        return cls(
            booking_id=booking.id,
            status=booking.status.value,
            start_at=booking.start_at,
            end_at=booking.end_at,
            customer_id=booking.customer_id,
            service_id=booking.service_id,
            reason=conflict.reason,
        )


class ConflictDetails(BaseModel):
    conflicts: list[ConflictResponse] = Field(
        description="Future bookings that no longer fit after this change. A warning, not an "
        "error: the change was applied and no booking was touched."
    )


class RuleWriteResponse(RuleResponse):
    details: ConflictDetails


class ExceptionWriteResponse(ExceptionResponse):
    details: ConflictDetails


class DeleteResponse(BaseModel):
    id: int = Field(description="The id of the removed rule or exception.")
    details: ConflictDetails

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"id": 4, "details": {"conflicts": []}}]}
    )
