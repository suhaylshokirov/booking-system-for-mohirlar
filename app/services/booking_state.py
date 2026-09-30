"""The only definition of which booking status changes are legal.

Pure: no database, no clock. The caller loads the booking and settings and
passes `now` (rule 5). `check_transition` decides; applying the change with a
guarded UPDATE and writing the history event is `services/booking.py` (P7.2).

Allowed changes (everything else is `InvalidTransition`):

    pending   -> confirmed   admin, before the booking starts
    pending   -> cancelled   its own customer before it starts, or an admin any time
                             (an admin cancels expired pendings, P7.7)
    confirmed -> cancelled   its own customer up to `start - cutoff`;
                             an admin before it starts, with a reason
    confirmed -> completed   admin, once `end_at` has passed
    cancelled, completed     terminal

Errors, all `AppError`: `InvalidTransition` (409 `INVALID_TRANSITION`),
`CancellationCutoffPassed` (409 `CANCELLATION_CUTOFF_PASSED`, `details.cutoff_at`),
`ReasonRequired` (422 `REASON_REQUIRED`), `TooEarlyToComplete` (409
`TOO_EARLY_TO_COMPLETE`, `details.end_at`).

Who may *see* a booking (someone else's is a 404) is decided before this is
called; a customer who is not the owner is still refused here as a backstop.
"""

from datetime import datetime, timedelta
from typing import Protocol

from app.core.errors import AppError
from app.models.booking import BookingStatus
from app.models.user import UserRole

# Every legal (from, to) pair. Who may do it and when is in `check_transition`.
ALLOWED: frozenset[tuple[BookingStatus, BookingStatus]] = frozenset(
    {
        (BookingStatus.PENDING, BookingStatus.CONFIRMED),
        (BookingStatus.PENDING, BookingStatus.CANCELLED),
        (BookingStatus.CONFIRMED, BookingStatus.CANCELLED),
        (BookingStatus.CONFIRMED, BookingStatus.COMPLETED),
    }
)


STALE_PENDING_REASON = "not confirmed in time"


def is_stale_pending(booking: "_Booking", now: datetime) -> bool:
    """A pending booking whose start has passed without anyone confirming it.

    It can no longer be confirmed and would sit as "pending" forever, so the
    admin list flags it and an admin cancels it (P7.7). No background job
    does that for them.
    """
    return booking.status == BookingStatus.PENDING and now >= booking.start_at


def cancellation_cutoff_at(start_at: datetime, cutoff_hours: int) -> datetime:
    """The last instant a customer may cancel a *confirmed* booking (inclusive).

    Shown to the customer before they book and on the booking page, so what
    they are told is exactly what `check_transition` enforces.
    """
    return start_at - timedelta(hours=cutoff_hours)


class _Booking(Protocol):
    status: BookingStatus
    customer_id: int
    start_at: datetime
    end_at: datetime


class _Actor(Protocol):
    id: int
    role: UserRole


class _Settings(Protocol):
    cancellation_cutoff_hours: int


class InvalidTransition(AppError):
    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__("INVALID_TRANSITION", message, status_code=409, details=details)


class CancellationCutoffPassed(AppError):
    def __init__(self, cutoff_at: datetime) -> None:
        super().__init__(
            "CANCELLATION_CUTOFF_PASSED",
            "It is too late to cancel this booking online. Please contact the business.",
            status_code=409,
            details={"cutoff_at": cutoff_at.isoformat()},
        )


class ReasonRequired(AppError):
    def __init__(self) -> None:
        super().__init__(
            "REASON_REQUIRED",
            "A reason is required to cancel a confirmed booking.",
            status_code=422,
        )


class TooEarlyToComplete(AppError):
    def __init__(self, end_at: datetime) -> None:
        super().__init__(
            "TOO_EARLY_TO_COMPLETE",
            "A booking can only be completed after it ends.",
            status_code=409,
            details={"end_at": end_at.isoformat()},
        )


def check_transition(
    booking: _Booking,
    to: BookingStatus,
    actor: _Actor,
    now: datetime,
    settings: _Settings,
    reason: str | None = None,
) -> None:
    """Return None if `actor` may move `booking` to `to` at `now`, else raise.

    Half-open time, like everywhere else: a customer may still cancel at exactly
    `start - cutoff`; completing is allowed at exactly `end_at`.
    """
    frm = booking.status
    if (frm, to) not in ALLOWED:
        raise InvalidTransition(
            f"A {frm.value} booking cannot become {to.value}.",
            {"from": frm.value, "to": to.value},
        )

    is_admin = actor.role == UserRole.ADMIN
    if not is_admin and not (to == BookingStatus.CANCELLED and actor.id == booking.customer_id):
        raise InvalidTransition(
            "You are not allowed to do that.", {"from": frm.value, "to": to.value}
        )

    started = now >= booking.start_at

    if to == BookingStatus.CONFIRMED:
        if started:
            raise InvalidTransition("This booking has already started.", {"from": frm.value})
    elif to == BookingStatus.COMPLETED:
        if now < booking.end_at:
            raise TooEarlyToComplete(booking.end_at)
    elif is_admin:
        # Cancelling. Expired pendings may be cleared by an admin; a confirmed
        # booking that has started is completed or left alone, not cancelled.
        if frm == BookingStatus.CONFIRMED:
            if started:
                raise InvalidTransition("This booking has already started.", {"from": frm.value})
            if not (reason and reason.strip()):
                raise ReasonRequired()
    elif frm == BookingStatus.PENDING:
        if started:
            raise CancellationCutoffPassed(booking.start_at)
    else:
        cutoff_at = cancellation_cutoff_at(booking.start_at, settings.cancellation_cutoff_hours)
        if now > cutoff_at:
            raise CancellationCutoffPassed(cutoff_at)
