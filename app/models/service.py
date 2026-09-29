"""`services` — what the business sells (a haircut, a beard trim).

Rules stored here: a service takes a positive number of minutes and costs zero
or more UZS (integer, no floats). It is deactivated with `is_active`, never
deleted, because bookings reference it; bookings also copy the price and
duration at booking time, so later edits here do not rewrite history.
"""

from sqlalchemy import CheckConstraint, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Service(TimestampMixin, Base):
    __tablename__ = "services"
    __table_args__ = (
        CheckConstraint("char_length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("duration_minutes > 0", name="duration_positive"),
        CheckConstraint("price >= 0", name="price_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(1000))
    duration_minutes: Mapped[int]
    # Whole UZS. Integer on purpose: no rounding, no float surprises.
    price: Mapped[int]
    is_active: Mapped[bool] = mapped_column(server_default=true())
