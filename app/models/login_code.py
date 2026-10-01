"""`login_codes` — the 6-digit codes emailed to people who sign up or sign in.

One row per request for a code. Only a keyed hash of the code is stored
(`security.hash_login_code`), never the code. A code is live while it is not
consumed, not expired and has fewer than the allowed wrong tries; asking for a
new one consumes the old ones, so at most one code per address works at a time.

A sign-in request for an address with no account, or a deactivated one, is
refused before any row is written (ADR 0013, amended 2026-10-01), so every row
is a code that was emailed.

`full_name` is set only for a sign-up request: the account is created when the
code is proven, from that name, so an address nobody controls never gets one.
"""

from datetime import datetime

from sqlalchemy import CheckConstraint, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class LoginCode(Base):
    __tablename__ = "login_codes"
    __table_args__ = (
        CheckConstraint("failed_attempts >= 0", name="attempts_not_negative"),
        CheckConstraint("expires_at > created_at", name="expires_after_created"),
        # "How many codes did this address ask for lately?" and "the live code".
        Index("ix_login_codes_email_created_at", "email", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254))  # trimmed and lower-cased
    code_hash: Mapped[str] = mapped_column(String(64))  # hex HMAC-SHA256
    full_name: Mapped[str | None] = mapped_column(String(100))
    # Set from the injected clock, not the database's, so tests can sit exactly on
    # the expiry boundary.
    created_at: Mapped[datetime]
    expires_at: Mapped[datetime]
    failed_attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    consumed_at: Mapped[datetime | None]
