"""Request and response models for weekly availability rules. Shape validation only.

Whether a time fits the slot grid and whether a rule overlaps another are
business rules and live in `services/availability.py`.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
