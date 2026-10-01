"""Request and response models for /auth. Shape validation only.

Email normalisation (trim + lower-case) is a business rule and lives in
`services/auth.py`; here we only reject input that cannot be an email at all.
There is no `email-validator` dependency (CLAUDE.md §3), so "looks like an
email" is one `local@domain.tld` pattern, which is all a booking system needs:
the real check is whether the person can be reached, not RFC 5322 minutiae.
"""

import re
from datetime import datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
)

from app.models.user import UserRole

_EMAIL_SHAPE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _check_email_shape(value: str) -> str:
    if not _EMAIL_SHAPE.fullmatch(value.strip()):
        raise ValueError("must be an email address like name@example.com")
    return value


# Lengths are checked after trimming, or "   " would pass and be stored as an
# empty name (the service trims before saving).
FullNameInput = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]

# 254 is the longest valid email address, and the width of `users.email`.
EmailInput = Annotated[str, Field(min_length=3, max_length=254), AfterValidator(_check_email_shape)]


class RegisterRequest(BaseModel):
    """Start signing up: where to send the code, and the name for the new account."""

    email: EmailInput
    full_name: FullNameInput

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "aziza@example.com", "full_name": "Aziza Karimova"}]
        }
    )


class LoginRequest(BaseModel):
    """Start signing in: where to send the code."""

    email: EmailInput

    model_config = ConfigDict(json_schema_extra={"examples": [{"email": "aziza@example.com"}]})


def _digits_only(value: object) -> object:
    """Accept "123 456" and "123-456" as people paste them from an email."""
    if isinstance(value, str):
        return value.replace(" ", "").replace("-", "")
    return value


# Exactly 6 digits, checked after removing the spaces and dashes above.
CodeInput = Annotated[
    str,
    BeforeValidator(_digits_only),
    StringConstraints(pattern=r"^\d{6}$"),
]


class VerifyRequest(BaseModel):
    """Finish signing up or in: the address and the 6-digit code emailed to it."""

    email: EmailInput
    code: CodeInput

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"email": "aziza@example.com", "code": "482913"}]}
    )


class CodeSentResponse(BaseModel):
    """The answer to asking for a code. It is the same whether or not the address has
    an account, on purpose: the endpoint cannot be used to find out who is registered."""

    message: str
    expires_in_minutes: int

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "message": "If this address can sign in, a 6-digit code is on its way.",
                    "expires_in_minutes": 10,
                }
            ]
        }
    )


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"access_token": "eyJhbGciOiJIUzI1NiIs...", "token_type": "bearer"}]
        }
    )


class UserResponse(BaseModel):
    id: int
    email: str
    full_name: str
    role: UserRole
    provider_id: int | None = Field(
        default=None,
        description="The provider a barber runs (use it in `/providers/{id}/...`); "
        "`null` for customers.",
    )
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    "id": 7,
                    "email": "aziza@example.com",
                    "full_name": "Aziza Karimova",
                    "role": "customer",
                    "provider_id": None,
                    "created_at": "2026-10-01T07:00:00Z",
                }
            ]
        },
    )
