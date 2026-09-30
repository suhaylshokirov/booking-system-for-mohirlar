"""Every reason a requested booking start can be invalid, in one pure module.

No database, no clock: the caller loads the facts (service, provider, working
windows) and passes `now`. `slots.compute_slots` uses the same helpers
(`earliest_start`, `horizon_end`, `grid_start_fits`), so the slot grid and this
validator cannot disagree about what is bookable.

This is the friendly check. The exclusion constraints in the database still
decide double-booking (ADR 0001); overlap is not checked here.

Every rule raises `AppError` with status 422 and its own code.
"""

from collections.abc import Iterable
from datetime import datetime, timedelta

from app.core.errors import AppError


def earliest_start(now: datetime, lead_time: timedelta) -> datetime:
    """First instant a booking may start (inclusive)."""
    return now + lead_time


def horizon_end(now: datetime, horizon_days: int) -> datetime:
    """First instant too far ahead to book (exclusive). An instant, not a calendar date."""
    return now + timedelta(days=horizon_days)


def grid_start_fits(
    start: datetime,
    window: tuple[datetime, datetime],
    duration: timedelta,
    granularity: timedelta,
) -> bool:
    """True iff `start` is on the window's grid and `[start, start + duration)` fits inside it."""
    window_start, window_end = window
    return (
        window_start <= start
        and start + duration <= window_end
        and (start - window_start) % granularity == timedelta(0)
    )


def validate_booking_start(
    *,
    service_active: bool,
    provider_active: bool,
    provider_offers_service: bool,
    start: datetime,
    windows_utc: Iterable[tuple[datetime, datetime]],
    duration: timedelta,
    granularity: timedelta,
    now: datetime,
    lead_time: timedelta,
    horizon_days: int,
) -> None:
    """Raise the first broken rule; return None if the start is bookable.

    Checked in this order: `SERVICE_INACTIVE`, `PROVIDER_INACTIVE`,
    `PROVIDER_DOES_NOT_OFFER_SERVICE`, `START_IN_PAST`, `INSIDE_LEAD_TIME`,
    `BEYOND_HORIZON`, `OUTSIDE_AVAILABILITY` (no working window on that local
    day holds the whole service, exceptions included, since `windows_utc`
    already has them applied), `NOT_ALIGNED` (it fits a window but is not on
    the granularity grid measured from the window start).
    """
    if not service_active:
        raise _invalid("SERVICE_INACTIVE", "This service is not available.")
    if not provider_active:
        raise _invalid("PROVIDER_INACTIVE", "This provider is not available.")
    if not provider_offers_service:
        raise _invalid(
            "PROVIDER_DOES_NOT_OFFER_SERVICE", "This provider does not offer that service."
        )
    if start < now:
        raise _invalid("START_IN_PAST", "That time has already passed.")
    earliest = earliest_start(now, lead_time)
    if start < earliest:
        raise _invalid(
            "INSIDE_LEAD_TIME",
            "That is too soon to book.",
            {"earliest": earliest.isoformat()},
        )
    last = horizon_end(now, horizon_days)
    if start >= last:
        raise _invalid(
            "BEYOND_HORIZON",
            "That is too far ahead to book.",
            {"before": last.isoformat()},
        )
    holding = [w for w in windows_utc if w[0] <= start and start + duration <= w[1]]
    if not holding:
        raise _invalid("OUTSIDE_AVAILABILITY", "The provider is not working at that time.")
    if not any(grid_start_fits(start, w, duration, granularity) for w in holding):
        raise _invalid(
            "NOT_ALIGNED",
            f"Start times are every {int(granularity.total_seconds() // 60)} minutes.",
        )


def _invalid(code: str, message: str, details: dict | None = None) -> AppError:
    return AppError(code, message, status_code=422, details=details)
