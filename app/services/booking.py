"""Creating bookings. The database, not this module, guarantees no double booking.

`create_booking` validates the request (`booking_rules`), then inserts a
`pending` booking and its first `booking_events` row in one transaction.

Why the overlap pre-check is not enough: two requests can both run the
pre-check, both see the slot free, and both insert. The pre-check only exists
to give the common case a friendly message before we touch the constraints.
The truth is the two Postgres exclusion constraints (`no_provider_overlap`,
`no_customer_overlap`); when the second insert loses the race, Postgres raises
SQLSTATE 23P01 and we map the constraint name to the same 409 the pre-check
would have given (ADR 0001).

`transition` changes a booking's status with a guarded UPDATE, so two
concurrent changes cannot both succeed (ADR 0008).
"""

import enum
from datetime import date, datetime, timedelta

from psycopg import errors as pg_errors
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.pagination import PageParams, paginate
from app.core.timezones import local_day_bounds_utc, utc_to_local
from app.models.availability import AvailabilityException, AvailabilityRule
from app.models.booking import Booking, BookingEvent, BookingStatus
from app.models.provider import Provider, ProviderService
from app.models.service import Service
from app.models.user import User, UserRole
from app.services.booking_rules import validate_booking_start
from app.services.booking_state import check_transition
from app.services.business_settings import get_business_settings
from app.services.slots import build_windows_for_date

# Statuses that hold time. Cancelled and completed bookings free it.
_ACTIVE = [BookingStatus.PENDING, BookingStatus.CONFIRMED]


def slot_taken() -> AppError:
    return AppError("SLOT_TAKEN", "That time was just taken. Please pick another.", status_code=409)


def customer_overlap() -> AppError:
    return AppError(
        "CUSTOMER_OVERLAP",
        "You already have a booking that overlaps this time.",
        status_code=409,
    )


# Constraint name -> the error it means. Names come from migration 0003.
_OVERLAP_ERRORS = {"no_provider_overlap": slot_taken, "no_customer_overlap": customer_overlap}


def create_booking(
    db: Session,
    customer: User,
    service_id: int,
    provider_id: int,
    start_at: datetime,
    notes: str | None,
    now: datetime,
) -> Booking:
    """Create a pending booking for `customer`; return it (flushed, not committed).

    `end_at` is `start_at` plus the service duration; price and duration are
    copied onto the booking so later edits to the service do not change it
    (ADR 0007). `start_at` must be timezone-aware.

    Raises: 404 `NOT_FOUND` (service or provider does not exist); 422 for any
    rule in `booking_rules.validate_booking_start`; 409 `SLOT_TAKEN` (provider
    busy) or 409 `CUSTOMER_OVERLAP` (customer busy with anyone), from the
    pre-check or, if a concurrent request won the race, from the database.
    """
    service = db.get(Service, service_id)
    provider = db.get(Provider, provider_id)
    if service is None:
        raise AppError("NOT_FOUND", "Service not found.", status_code=404)
    if provider is None:
        raise AppError("NOT_FOUND", "Provider not found.", status_code=404)

    settings = get_business_settings(db)
    duration = timedelta(minutes=service.duration_minutes)
    day = utc_to_local(start_at, settings.timezone).date()
    validate_booking_start(
        service_active=service.is_active,
        provider_active=provider.is_active,
        provider_offers_service=db.get(ProviderService, (provider_id, service_id)) is not None,
        start=start_at,
        windows_utc=_working_windows(db, provider_id, day, settings.timezone),
        duration=duration,
        granularity=timedelta(minutes=settings.slot_granularity_minutes),
        now=now,
        lead_time=timedelta(minutes=settings.min_lead_time_minutes),
        horizon_days=settings.max_booking_horizon_days,
    )

    end_at = start_at + duration
    _precheck_overlap(db, customer.id, provider_id, start_at, end_at)

    booking = Booking(
        customer_id=customer.id,
        provider_id=provider_id,
        service_id=service_id,
        start_at=start_at,
        end_at=end_at,
        status=BookingStatus.PENDING,
        price_amount=service.price,
        duration_minutes=service.duration_minutes,
        notes=notes,
    )
    # A savepoint: if the constraint rejects the insert, only this block is
    # undone and the caller's transaction stays usable.
    try:
        with db.begin_nested():
            db.add(booking)
            db.flush()
            db.add(
                BookingEvent(
                    booking_id=booking.id,
                    from_status=None,
                    to_status=BookingStatus.PENDING,
                    actor_id=customer.id,
                )
            )
            db.flush()
    except IntegrityError as exc:
        raise _map_overlap_error(exc) from exc
    return booking


def _working_windows(db: Session, provider_id: int, day, timezone: str):
    rules = db.scalars(select(AvailabilityRule).where(AvailabilityRule.provider_id == provider_id))
    exception = db.scalar(
        select(AvailabilityException).where(
            AvailabilityException.provider_id == provider_id, AvailabilityException.date == day
        )
    )
    return build_windows_for_date(list(rules), exception, day, timezone)


def _precheck_overlap(
    db: Session, customer_id: int, provider_id: int, start_at: datetime, end_at: datetime
) -> None:
    """Friendly early 409s. Provider first, matching which constraint would fire."""
    for column, value, error in (
        (Booking.provider_id, provider_id, slot_taken),
        (Booking.customer_id, customer_id, customer_overlap),
    ):
        clash = db.scalar(
            select(Booking.id)
            .where(
                column == value,
                Booking.status.in_(_ACTIVE),
                Booking.start_at < end_at,
                Booking.end_at > start_at,
            )
            .limit(1)
        )
        if clash is not None:
            raise error()


def _map_overlap_error(exc: IntegrityError) -> Exception:
    """Turn an exclusion violation into its 409; anything else is a real bug, re-raise it."""
    orig = exc.orig
    if isinstance(orig, pg_errors.ExclusionViolation):
        make_error = _OVERLAP_ERRORS.get(orig.diag.constraint_name or "")
        if make_error is not None:
            return make_error()
    return exc


class Scope(enum.StrEnum):
    UPCOMING = "upcoming"
    PAST = "past"


def list_my_bookings(
    db: Session,
    user: User,
    params: PageParams,
    now: datetime,
    scope: Scope | None = None,
    status: BookingStatus | None = None,
) -> tuple[list[Booking], int]:
    """One page of the user's own bookings, and the total.

    `upcoming` means not yet over (`end_at > now`, so one in progress still
    counts), soonest first; `past` is the rest, most recent first. Without a
    scope, everything, newest start first. Ties break by id so pages are stable.
    """
    query = select(Booking).where(Booking.customer_id == user.id)
    if status is not None:
        query = query.where(Booking.status == status)
    if scope is Scope.UPCOMING:
        query = query.where(Booking.end_at > now).order_by(Booking.start_at, Booking.id)
    elif scope is Scope.PAST:
        query = query.where(Booking.end_at <= now).order_by(Booking.start_at.desc(), Booking.id)
    else:
        query = query.order_by(Booking.start_at.desc(), Booking.id)
    return paginate(db, query, params)


def list_all_bookings(
    db: Session,
    params: PageParams,
    status: BookingStatus | None = None,
    provider_id: int | None = None,
    customer_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[Booking], int]:
    """One page of every booking (the caller has checked the user is an admin), and the total.

    `date_from` / `date_to` are calendar days on the business's clock, both
    inclusive: a booking matches if it *starts* on one of those local days. They
    become UTC instants here so the DST-correct conversion stays in
    `core/timezones`. Soonest start first (ties by id), which is the order an
    admin runs the day in.
    """
    query = select(Booking)
    if status is not None:
        query = query.where(Booking.status == status)
    if provider_id is not None:
        query = query.where(Booking.provider_id == provider_id)
    if customer_id is not None:
        query = query.where(Booking.customer_id == customer_id)
    if date_from is not None or date_to is not None:
        timezone = get_business_settings(db).timezone
        if date_from is not None:
            query = query.where(Booking.start_at >= local_day_bounds_utc(date_from, timezone)[0])
        if date_to is not None:
            query = query.where(Booking.start_at < local_day_bounds_utc(date_to, timezone)[1])
    return paginate(db, query.order_by(Booking.start_at, Booking.id), params)


def get_booking(db: Session, user: User, booking_id: int) -> Booking:
    """A booking the user may see: their own, or any for an admin.

    Raises: 404 `BOOKING_NOT_FOUND`, the same for "does not exist" and "belongs
    to someone else", so ids cannot be probed (404, not 403).
    """
    booking = db.get(Booking, booking_id)
    if booking is None or (user.role != UserRole.ADMIN and booking.customer_id != user.id):
        raise AppError("BOOKING_NOT_FOUND", "Booking not found.", status_code=404)
    return booking


def transition(
    db: Session,
    actor: User,
    booking_id: int,
    to: BookingStatus,
    now: datetime,
    reason: str | None = None,
) -> Booking:
    """Move a booking to `to` and record the change; return it (flushed, not committed).

    Order matters: find the booking as `actor` (someone else's is a 404), ask
    the state machine if the change is legal, then apply it with
    `UPDATE ... WHERE id = :id AND status = :expected`. If another request
    changed the status after we read it, no row matches and we stop before
    writing an event, so the history never shows a change that did not happen.
    The status update and its `booking_events` row share the caller's
    transaction (ADR 0008).

    Raises: 404 `BOOKING_NOT_FOUND`; the `booking_state` errors (409
    `INVALID_TRANSITION`, `CANCELLATION_CUTOFF_PASSED`, `TOO_EARLY_TO_COMPLETE`,
    422 `REASON_REQUIRED`); 409 `BOOKING_STATE_CHANGED` when we lost a race.
    """
    booking = get_booking(db, actor, booking_id)
    check_transition(booking, to, actor, now, get_business_settings(db), reason)

    expected = booking.status
    values: dict = {"status": to}
    if to == BookingStatus.CANCELLED:
        values |= {"cancelled_by_id": actor.id, "cancel_reason": reason}
    result = db.execute(
        update(Booking)
        .where(Booking.id == booking.id, Booking.status == expected)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount == 0:
        raise AppError(
            "BOOKING_STATE_CHANGED",
            "This booking was just changed by someone else. Reload and try again.",
            status_code=409,
        )
    db.add(
        BookingEvent(
            booking_id=booking.id,
            from_status=expected,
            to_status=to,
            actor_id=actor.id,
            reason=reason,
        )
    )
    db.flush()
    # The UPDATE bypassed the ORM object; reload it so callers see the new state.
    db.refresh(booking)
    return booking
