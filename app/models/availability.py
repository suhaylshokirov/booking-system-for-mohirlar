"""`availability_rules` (weekly hours) and `availability_exceptions` (one-off days).

Times here are **local wall-clock** times in the business timezone
(`business_settings.timezone`), stored as `time` / `date`, not `timestamptz`.
"Mondays 09:00-18:00" means 09:00 in Tashkent whatever the UTC offset; the
conversion to UTC instants happens in one module only (P4.1).

A window cannot cross midnight: `end_time` must be later than `start_time` on
the same day. A late shift is two rules (or ends at 23:59).

Rules for one provider on one weekday must not overlap. That is an exclusion
constraint (`no_availability_rule_overlap`), which the ORM cannot express
usefully, so it is created in migration 0001, not here.
"""

from datetime import date, time

from sqlalchemy import CheckConstraint, ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class AvailabilityRule(TimestampMixin, Base):
    """A recurring weekly window: this provider works `weekday`, `start_time`-`end_time`."""

    __tablename__ = "availability_rules"
    __table_args__ = (
        # 0 = Monday ... 6 = Sunday, the same numbering as Python's
        # `date.weekday()`, so no translation layer is needed.
        CheckConstraint("weekday BETWEEN 0 AND 6", name="weekday_range"),
        CheckConstraint("end_time > start_time", name="end_after_start"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="RESTRICT"))
    weekday: Mapped[int] = mapped_column(SmallInteger)
    start_time: Mapped[time]
    end_time: Mapped[time]


class AvailabilityException(TimestampMixin, Base):
    """An override for one date: a day off, or different hours than the weekly rule.

    `start_time` and `end_time` are both NULL (day off) or both set (custom
    hours replacing the weekly rules for that date) — never one of each.
    """

    __tablename__ = "availability_exceptions"
    __table_args__ = (
        CheckConstraint(
            "(start_time IS NULL AND end_time IS NULL)"
            " OR (start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time)",
            name="day_off_or_valid_hours",
        ),
        # One override per provider per date; two would disagree about the day.
        UniqueConstraint("provider_id", "date", name="uq_availability_exceptions_provider_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_id: Mapped[int] = mapped_column(ForeignKey("providers.id", ondelete="RESTRICT"))
    date: Mapped[date]
    start_time: Mapped[time | None]
    end_time: Mapped[time | None]
    reason: Mapped[str | None] = mapped_column(String(200))
