"""`users` — people who can log in: customers and barbers.

Rules stored here: the email is unique ignoring case (so `Ali@x.uz` and
`ali@x.uz` cannot both register), and a user is deactivated with `is_active`,
never deleted, because bookings reference them.

A barber is a user linked to exactly one provider (`provider_id`), and only
barbers have one: a CHECK ties the role to the link, and a unique constraint
gives each provider at most one login. There is no separate administrator
(ADR 0010): barbers manage their own bookings, hours and profile.

There is no password: a person proves they own the email by typing the code
sent to it (`login_codes`, ADR 0013).
"""

import enum

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserRole(enum.StrEnum):
    CUSTOMER = "customer"
    BARBER = "barber"


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness. A plain UNIQUE on `email` would treat
        # `Ali@x.uz` and `ali@x.uz` as different people. The service lower-cases
        # input too, but this index is the guarantee.
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
        # A barber is the login of one provider; nobody else has a provider.
        CheckConstraint(
            "(role = 'barber') = (provider_id IS NOT NULL)", name="barber_has_provider"
        ),
        UniqueConstraint("provider_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254))  # 254 = longest valid email address
    full_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[UserRole] = mapped_column(
        # Store the lowercase value ('customer'), not the Python member name.
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        server_default=UserRole.CUSTOMER.value,
    )
    # Set for barbers only (see the CHECK above).
    provider_id: Mapped[int | None] = mapped_column(ForeignKey("providers.id", ondelete="RESTRICT"))
    is_active: Mapped[bool] = mapped_column(server_default=true())
