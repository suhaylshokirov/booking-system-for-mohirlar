"""`users` — people who can log in: customers and the business admin.

Rules stored here: the email is unique ignoring case (so `Ali@x.uz` and
`ali@x.uz` cannot both register), and a user is deactivated with `is_active`,
never deleted, because bookings reference them.
"""

import enum

from sqlalchemy import Enum, Index, String, text, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserRole(enum.StrEnum):
    CUSTOMER = "customer"
    ADMIN = "admin"


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        # Case-insensitive uniqueness. A plain UNIQUE on `email` would treat
        # `Ali@x.uz` and `ali@x.uz` as different people. The service lower-cases
        # input too, but this index is the guarantee.
        Index("uq_users_email_lower", text("lower(email)"), unique=True),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254))  # 254 = longest valid email address
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[UserRole] = mapped_column(
        # Store the lowercase value ('customer'), not the Python member name.
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        server_default=UserRole.CUSTOMER.value,
    )
    is_active: Mapped[bool] = mapped_column(server_default=true())
