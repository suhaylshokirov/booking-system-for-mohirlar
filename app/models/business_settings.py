"""`business_settings` — the one row of business-wide configuration.

The single row is enforced by `CHECK (id = 1)` plus the primary key: a second
row would need a different id, which the CHECK refuses. The booking rules
(lead time, horizon, cancellation cutoff) live here so the admin can change
them without a deploy.
"""

from sqlalchemy import CheckConstraint, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BusinessSettings(TimestampMixin, Base):
    __tablename__ = "business_settings"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        CheckConstraint("char_length(btrim(name)) > 0", name="name_not_blank"),
        CheckConstraint("slot_granularity_minutes > 0", name="granularity_positive"),
        CheckConstraint("min_lead_time_minutes >= 0", name="lead_time_not_negative"),
        CheckConstraint("max_booking_horizon_days > 0", name="horizon_positive"),
        CheckConstraint("cancellation_cutoff_hours >= 0", name="cutoff_not_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, server_default="1")
    name: Mapped[str] = mapped_column(String(100))
    # IANA name, e.g. 'Asia/Tashkent'. Availability is wall-clock time in this
    # zone; the app validates the name against `zoneinfo` (P3.1).
    timezone: Mapped[str] = mapped_column(String(64), server_default="Asia/Tashkent")
    # ISO 4217 code. Prices are integers in this currency's whole units.
    currency: Mapped[str] = mapped_column(String(3), server_default="UZS")
    # Slots start on multiples of this many minutes after the window opens.
    slot_granularity_minutes: Mapped[int] = mapped_column(server_default="15")
    min_lead_time_minutes: Mapped[int] = mapped_column(server_default="60")
    max_booking_horizon_days: Mapped[int] = mapped_column(server_default="60")
    cancellation_cutoff_hours: Mapped[int] = mapped_column(server_default="2")
