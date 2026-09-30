"""Load exactly the data `compute_slots` needs, and group the answer by provider.

Rules:
* A missing or inactive service or provider is 404 `NOT_FOUND`: customers must
  not be able to tell "inactive" from "never existed" (same as the catalogs).
* A provider that does not offer the service is 422
  `PROVIDER_DOES_NOT_OFFER_SERVICE`. Without a `provider_id`, every active
  provider offering the service is returned, including ones with no free slot
  that day, so the UI can say so.
* `date` is a local date in the business timezone. Busy time is every pending
  or confirmed booking of the provider that overlaps that local day; cancelled
  and completed bookings free their time.
* `day` must lie in `[today, today + max_booking_horizon_days]`, where today is
  the current date on the business's wall clock; otherwise 422
  `DATE_OUT_OF_RANGE`. This is checked before anything is loaded.
* The horizon ends `max_booking_horizon_days` after `now` (an instant, not a
  calendar date). Booking validation (P6.1) must use the same value.

This only reads. The list is advisory: a slot shown here can still be lost to a
concurrent booking, and the exclusion constraint decides that (ADR 0001).
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.timezones import local_day_bounds_utc, utc_to_local
from app.models.availability import AvailabilityException, AvailabilityRule
from app.models.booking import Booking, BookingStatus
from app.models.business_settings import BusinessSettings
from app.models.provider import Provider, ProviderService
from app.models.service import Service
from app.services.booking_rules import horizon_end
from app.services.business_settings import get_business_settings
from app.services.slots import build_windows_for_date, compute_slots


@dataclass(frozen=True)
class ProviderSlots:
    provider: Provider
    starts: list[datetime]  # UTC, sorted; each slot lasts the service duration


@dataclass(frozen=True)
class SlotsResult:
    service: Service
    date: date
    timezone: str
    providers: list[ProviderSlots]


def get_slots(
    db: Session, service_id: int, day: date, provider_id: int | None, now: datetime
) -> SlotsResult:
    """Free start times for `service_id` on local date `day`, grouped by provider.

    Raises: 404 `NOT_FOUND` (service or provider missing/inactive), 422
    `PROVIDER_DOES_NOT_OFFER_SERVICE`, 422 `DATE_OUT_OF_RANGE`.
    """
    service = db.get(Service, service_id)
    if service is None or not service.is_active:
        raise AppError("NOT_FOUND", "Service not found.", status_code=404)

    providers = _providers(db, service_id, provider_id)
    settings = get_business_settings(db)
    tz = settings.timezone
    today, last_day = bookable_dates(settings, now)
    if not today <= day <= last_day:
        raise AppError(
            "DATE_OUT_OF_RANGE",
            f"Pick a date from {today} to {last_day}.",
            status_code=422,
            details={"earliest": today.isoformat(), "latest": last_day.isoformat()},
        )
    day_start, day_end = local_day_bounds_utc(day, tz)
    ids = [p.id for p in providers]

    rules: dict[int, list[AvailabilityRule]] = defaultdict(list)
    for rule in db.scalars(select(AvailabilityRule).where(AvailabilityRule.provider_id.in_(ids))):
        rules[rule.provider_id].append(rule)
    exceptions = {
        row.provider_id: row
        for row in db.scalars(
            select(AvailabilityException).where(
                AvailabilityException.provider_id.in_(ids), AvailabilityException.date == day
            )
        )
    }
    busy: dict[int, list[tuple[datetime, datetime]]] = defaultdict(list)
    for booking in db.scalars(
        select(Booking).where(
            Booking.provider_id.in_(ids),
            Booking.status.in_([BookingStatus.PENDING, BookingStatus.CONFIRMED]),
            Booking.start_at < day_end,
            Booking.end_at > day_start,
        )
    ):
        busy[booking.provider_id].append((booking.start_at, booking.end_at))

    grouped = []
    for provider in providers:
        windows = build_windows_for_date(rules[provider.id], exceptions.get(provider.id), day, tz)
        starts = compute_slots(
            windows,
            busy[provider.id],
            timedelta(minutes=service.duration_minutes),
            timedelta(minutes=settings.slot_granularity_minutes),
            now,
            timedelta(minutes=settings.min_lead_time_minutes),
            horizon_end(now, settings.max_booking_horizon_days),
        )
        grouped.append(ProviderSlots(provider, starts))
    return SlotsResult(service, day, tz, grouped)


def bookable_dates(settings: BusinessSettings, now: datetime) -> tuple[date, date]:
    """The first and last local date slots may be asked for (both inclusive).

    Today on the business's wall clock, through `max_booking_horizon_days`
    later. The booking page uses it for its date picker's limits, so the
    picker and `get_slots` cannot disagree.
    """
    today = utc_to_local(now, settings.timezone).date()
    return today, today + timedelta(days=settings.max_booking_horizon_days)


def _providers(db: Session, service_id: int, provider_id: int | None) -> list[Provider]:
    """The active providers to compute for, validated against the service."""
    if provider_id is not None:
        provider = db.get(Provider, provider_id)
        if provider is None or not provider.is_active:
            raise AppError("NOT_FOUND", "Provider not found.", status_code=404)
        offered = db.get(ProviderService, (provider_id, service_id))
        if offered is None:
            raise AppError(
                "PROVIDER_DOES_NOT_OFFER_SERVICE",
                "This provider does not offer that service.",
                status_code=422,
                details={"provider_id": provider_id, "service_id": service_id},
            )
        return [provider]
    return list(
        db.scalars(
            select(Provider)
            .join(ProviderService, ProviderService.provider_id == Provider.id)
            .where(ProviderService.service_id == service_id, Provider.is_active)
            .order_by(Provider.name, Provider.id)
        )
    )
