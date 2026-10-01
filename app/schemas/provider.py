"""Request and response models for /providers. Shape validation only."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.provider import Provider
from app.schemas.service import ServiceResponse
from app.schemas.types import PhoneNumber

# More offered services than this cannot exist in a small business; the cap
# just keeps one request bounded.
MAX_OFFERED_SERVICES = 200

_EXAMPLE = {
    "name": "Jasur",
    "bio": "Ten years of classic cuts and fades.",
    "phone": "+998901234567",
}


def photo_url(provider: Provider) -> str | None:
    """Where pages and API clients fetch a provider's photo, or None if there is none.

    The `v` query changes whenever the provider row does, so a browser that
    cached the old picture asks again after a new one is uploaded.
    """
    if provider.photo_type is None:
        return None
    version = int(provider.updated_at.timestamp() * 1_000_000)
    return f"/api/v1/providers/{provider.id}/photo?v={version}"


def _blank_to_none(value: str | None) -> str | None:
    return value or None


def _blank_text_to_none(value: object) -> object:
    """An empty phone field means "no number", not an invalid one."""
    return None if isinstance(value, str) and not value.strip() else value


class ProviderUpdate(BaseModel):
    """A partial update: send only the fields to change.

    `bio: null` or `phone: null` clears it; the name cannot be null. A phone
    number needs its country code and is stored without spaces (E.164).
    """

    name: str | None = Field(default=None, min_length=1, max_length=100)
    bio: str | None = Field(default=None, max_length=1000)
    phone: PhoneNumber | None = Field(
        default=None,
        description="With the country code. Spaces, dashes and brackets are dropped: "
        "`+998 90 123-45-67` is stored as `+998901234567`.",
    )

    model_config = ConfigDict(
        str_strip_whitespace=True,
        json_schema_extra={
            "examples": [{"bio": "Now also fades."}, {"phone": "+998 90 123 45 67"}]
        },
    )

    _blank_bio = field_validator("bio")(_blank_to_none)
    _blank_phone = field_validator("phone", mode="before")(_blank_text_to_none)

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
    phone: str | None = Field(description="E.164, such as `+998901234567`; `null` if not given.")
    photo_url: str | None = Field(
        description="Where to fetch the photo (`GET /providers/{id}/photo`); `null` if none. "
        "The `v` query changes when the provider does, so it is safe to cache."
    )
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
                    "photo_url": "/api/v1/providers/1/photo?v=1790845200000000",
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
            phone=provider.phone,
            photo_url=photo_url(provider),
            is_active=provider.is_active,
            services=[ServiceResponse.model_validate(s) for s in view.services],
            created_at=provider.created_at,
            updated_at=provider.updated_at,
        )
