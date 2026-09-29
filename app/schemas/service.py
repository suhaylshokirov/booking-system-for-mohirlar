"""Request and response models for /services. Shape validation only.

That a duration fits the slot grid depends on the business settings, so it is
checked in `services/service_catalog.py`, not here.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Longest a single appointment can be: one working day.
MAX_DURATION_MINUTES = 480
# The price column is a 32-bit integer; this is its ceiling, so an absurd
# value is a clean 422 rather than a database error.
MAX_PRICE = 2_147_483_647

_EXAMPLE = {
    "name": "Haircut",
    "description": "Wash, cut and style.",
    "duration_minutes": 30,
    "price": 60000,
}


def _blank_to_none(value: str | None) -> str | None:
    return value or None


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    # strict=True: money and minutes are whole numbers, so 45.5 or "45" is an
    # error instead of being quietly converted.
    duration_minutes: int = Field(gt=0, le=MAX_DURATION_MINUTES, strict=True)
    price: int = Field(ge=0, le=MAX_PRICE, strict=True, description="Whole UZS.")

    # Whitespace is trimmed before the length checks, so a name of only spaces is refused.
    model_config = ConfigDict(str_strip_whitespace=True, json_schema_extra={"examples": [_EXAMPLE]})

    _blank_description = field_validator("description")(_blank_to_none)


class ServiceUpdate(BaseModel):
    """A partial update: send only the fields to change.

    `description: null` clears the description; the other fields cannot be null.
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    duration_minutes: int | None = Field(default=None, gt=0, le=MAX_DURATION_MINUTES, strict=True)
    price: int | None = Field(default=None, ge=0, le=MAX_PRICE, strict=True)

    model_config = ConfigDict(
        str_strip_whitespace=True, json_schema_extra={"examples": [{"price": 70000}]}
    )

    _blank_description = field_validator("description")(_blank_to_none)

    @model_validator(mode="after")
    def _only_real_values(self) -> "ServiceUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        for field in self.model_fields_set - {"description"}:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null; omit it to leave it unchanged")
        return self


class ServiceResponse(BaseModel):
    id: int
    name: str
    description: str | None
    duration_minutes: int
    price: int = Field(description="Whole UZS.")
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 1,
                    **_EXAMPLE,
                    "is_active": True,
                    "created_at": "2026-10-01T07:00:00Z",
                    "updated_at": "2026-10-01T07:00:00Z",
                }
            ]
        },
    )
