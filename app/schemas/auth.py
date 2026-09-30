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

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

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
    email: EmailInput
    # 128 caps the work Argon2 does on one request; 8 is the usual floor.
    password: str = Field(min_length=8, max_length=128)
    full_name: FullNameInput

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "email": "aziza@example.com",
                    "password": "a long passphrase",
                    "full_name": "Aziza Karimova",
                }
            ]
        }
    )


class LoginRequest(BaseModel):
    email: EmailInput
    # No minimum: a wrong password of any length is just "incorrect".
    password: str = Field(min_length=1, max_length=128)

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [{"email": "aziza@example.com", "password": "a long passphrase"}]
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
                    "created_at": "2026-10-01T07:00:00Z",
                }
            ]
        },
    )
