"""The numbers on the admin dashboard: today, the pending queue, this week's utilization.

Business rules:

* "Today" and "this week" are the business's local calendar (Monday to Sunday),
  converted to UTC instants by `core/timezones`, so a booking at 23:30 local
  belongs to the local day it happens on.
* *Today's bookings* counts bookings that start today and are not cancelled
  (pending, confirmed and completed): the day's workload, not its history.
* *Pending* is every pending booking, whenever it is. One whose start has
  passed is flagged `is_stale` (`booking_state.is_stale_pending`): it can no
  longer be confirmed, only cleared.
* *Utilization* = booked minutes ÷ available minutes for this local week.
  Available minutes are the working windows (`slots.build_windows_for_date`,
  so exceptions and days off count) of every **active** provider. Booked
  minutes are the duration snapshots of the non-cancelled bookings that start
  this week. It is `None` (shown as a dash) when nothing is available, and
  capped at 100% in case hours were cut after bookings were made.

Read-only; it raises nothing.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timezones import local_day_bounds_utc, utc_to_local
from app.models.availability import AvailabilityException, AvailabilityRule
from app.models.booking import Booking, BookingStatus
from app.models.provider import Provider
from app.models.user import User
from app.services.booking import BookingLine, describe_bookings
from app.services.booking_state import is_stale_pending
from app.services.business_settings import get_business_settings
from app.services.slots import build_windows_for_date

PENDING_SHOWN = 50  # the queue is for acting on; past this, use the bookings list


@dataclass(frozen=True)
class PendingRow:
    line: BookingLine
    customer_name: str
    customer_email: str
    is_stale: bool


@dataclass(frozen=True)
class Dashboard:
    today_count: int
    pending_count: int
    booked_minutes: int
    available_minutes: int
    utilization_percent: int | None
    pending: list[PendingRow]


def get_dashboard(db: Session, now: datetime) -> Dashboard:
    settings = get_business_settings(db)
    tz = settings.timezone
    today = utc_to_local(now, tz).date()
    day_start, day_end = local_day_bounds_utc(today, tz)
    monday = today - timedelta(days=today.weekday())
    week_start = local_day_bounds_utc(monday, tz)[0]
    week_end = local_day_bounds_utc(monday + timedelta(days=6), tz)[1]

    not_cancelled = Booking.status != BookingStatus.CANCELLED
    today_count = db.scalar(
        select(func.count(Booking.id)).where(
            not_cancelled, Booking.start_at >= day_start, Booking.start_at < day_end
        )
    )
    pending_count = db.scalar(
        select(func.count(Booking.id)).where(Booking.status == BookingStatus.PENDING)
    )
    booked = db.scalar(
        select(func.coalesce(func.sum(Booking.duration_minutes), 0)).where(
            not_cancelled, Booking.start_at >= week_start, Booking.start_at < week_end
        )
    )

    available = _available_minutes(db, monday, tz)
    utilization = None if available == 0 else min(100, round(100 * booked / available))

    bookings = list(
        db.scalars(
            select(Booking)
            .where(Booking.status == BookingStatus.PENDING)
            .order_by(Booking.start_at, Booking.id)
            .limit(PENDING_SHOWN)
        )
    )
    customers = {
        user.id: user
        for user in db.scalars(select(User).where(User.id.in_({b.customer_id for b in bookings})))
    }
    pending = [
        PendingRow(
            line,
            customers[line.booking.customer_id].full_name,
            customers[line.booking.customer_id].email,
            is_stale_pending(line.booking, now),
        )
        for line in describe_bookings(db, bookings)
    ]
    return Dashboard(today_count, pending_count, booked, available, utilization, pending)


def _available_minutes(db: Session, monday: date, tz: str) -> int:
    """Working minutes of every active provider from `monday` through Sunday."""
    providers = list(db.scalars(select(Provider.id).where(Provider.is_active)))
    days = [monday + timedelta(days=i) for i in range(7)]
    rules = defaultdict(list)
    for rule in db.scalars(
        select(AvailabilityRule).where(AvailabilityRule.provider_id.in_(providers))
    ):
        rules[rule.provider_id].append(rule)
    exceptions = {
        (row.provider_id, row.date): row
        for row in db.scalars(
            select(AvailabilityException).where(
                AvailabilityException.provider_id.in_(providers),
                AvailabilityException.date.in_(days),
            )
        )
    }
    total = timedelta()
    for provider_id in providers:
        for day in days:
            windows = build_windows_for_date(
                rules[provider_id], exceptions.get((provider_id, day)), day, tz
            )
            total += sum((end - start for start, end in windows), timedelta())
    return int(total.total_seconds() // 60)
