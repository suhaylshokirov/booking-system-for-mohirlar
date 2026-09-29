"""Request and response models for /providers. Shape validation only."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.service import ServiceResponse

# More offered services than this cannot exist in a small business; the cap
# just keeps one request bounded.
MAX_OFFERED_SERVICES = 200

_EXAMPLE = {"name": "Jasur", "bio": "Ten years of classic cuts and fades."}


def _blank_to_none(value: str | None) -> str | None:
    return value or None


class ProviderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    bio: str | None = Field(default=None, max_length=1000)

    # Whitespace is trimmed before the length checks, so a name of only spaces is refused.
    model_config = ConfigDict(str_strip_whitespace=True, json_schema_extra={"examples": [_EXAMPLE]})

    _blank_bio = field_validator("bio")(_blank_to_none)


class ProviderUpdate(BaseModel):
    """A partial update: send only the fields to change.

    `bio: null` clears the bio; the name cannot be null.
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    bio: str | None = Field(default=None, max_length=1000)

    model_config = ConfigDict(
        str_strip_whitespace=True, json_schema_extra={"examples": [{"bio": "Now also fades."}]}
    )

    _blank_bio = field_validator("bio")(_blank_to_none)

    @model_validator(mode="after")
    def _only_real_values(self) -> "ProviderUpdate":
        if not self.model_fields_set:
            raise ValueError("send at least one field to change")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null; omit it to leave it unchanged")
        return self


class OfferedServices(BaseModel):
    service_ids: list[int] = Field(max_length=MAX_OFFERED_SERVICES)

    model_config = ConfigDict(json_schema_extra={"examples": [{"service_ids": [1, 2]}]})


class ProviderResponse(BaseModel):
    id: int
    name: str
    bio: str | None
    is_active: bool
    services: list[ServiceResponse] = Field(
        description="What this provider offers. Customers see only active services."
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "id": 1,
                    **_EXAMPLE,
                    "is_active": True,
                    "services": [],
                    "created_at": "2026-10-01T07:00:00Z",
                    "updated_at": "2026-10-01T07:00:00Z",
                }
            ]
        }
    )

    @classmethod
    def from_view(cls, view: Any) -> "ProviderResponse":
        """Build from a `ProviderView` (a provider plus the services to show)."""
        provider = view.provider
        return cls(
            id=provider.id,
            name=provider.name,
            bio=provider.bio,
            is_active=provider.is_active,
            services=[ServiceResponse.model_validate(s) for s in view.services],
            created_at=provider.created_at,
            updated_at=provider.updated_at,
        )
