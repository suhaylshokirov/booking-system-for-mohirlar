"""A customer's own bookings in the browser: the list, one booking, and Cancel.

    GET  /me/bookings                     Upcoming / Past tabs (`?tab=past`)
    GET  /me/bookings/{id}                one booking, its history, and Cancel
    GET  /me/bookings/{id}/ics            the booking as a calendar file
    POST /me/bookings/{id}/cancel         cancel it: `booking.transition`

Everything here needs a signed-in user (a visitor is sent to log in and back).
Only the user's own bookings appear, barbers included: someone else's booking
is the same 404 page as one that does not exist (`get_own_booking`), so ids
cannot be probed.

The Cancel button is shown only when `booking_state.can_cancel` says the
server would accept it, so the page and the rule cannot disagree. Past the
cutoff the page explains why instead of hiding the button silently. If the
button was pressed anyway (a page left open, or a race with the business
confirming), the detail page comes back with the reason and status 409.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.api.deps import CurrentUser
from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.core.errors import AppError
from app.models.booking import BookingEvent, BookingStatus
from app.models.user import User
from app.services import booking as booking_service
from app.services.booking import Scope
from app.services.booking_state import can_cancel, cancellation_cutoff_at
from app.services.business_settings import get_business_settings
from app.services.calendar import booking_ics
from app.web.paging import MAX_PAGE, make_pager, page_params
from app.web.templating import render, set_flash

router = APIRouter(include_in_schema=False)

ClockDep = Annotated[Clock, Depends(get_clock)]

BOOKINGS_PER_PAGE = 10


@dataclass(frozen=True)
class TimelineEntry:
    at: datetime  # UTC
    text: str
    reason: str | None


def describe_event(event: BookingEvent, actor: User | None, viewer: User) -> TimelineEntry:
    """One history row as a sentence a customer can read.

    Staff are "the business", not named: a customer has no need for a barber's
    name. No actor means the system acted.
    """
    if actor is None:
        who = "automatically"
    elif actor.id == viewer.id:
        who = "you"
    else:
        who = "the business"

    match event.to_status:
        case BookingStatus.PENDING:
            text = "Requested by you" if who == "you" else "Requested"
        case BookingStatus.CONFIRMED:
            text = "Confirmed by the business"
        case BookingStatus.COMPLETED:
            text = "Marked as completed"
        case BookingStatus.CANCELLED:
            text = "Cancelled" if who == "automatically" else f"Cancelled by {who}"
    return TimelineEntry(event.created_at, text, event.reason)


@router.get("/me/bookings", response_class=HTMLResponse, name="my_bookings")
def my_bookings(
    request: Request,
    db: DbSession,
    clock: ClockDep,
    user: CurrentUser,
    tab: Scope = Scope.UPCOMING,
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
) -> HTMLResponse:
    """Raises: 404 for a page past the last; 422 for a tab that is neither."""
    items, total = booking_service.list_my_bookings(
        db, user, page_params(page, BOOKINGS_PER_PAGE), clock.now(), tab
    )
    context = {
        "business": get_business_settings(db),
        "lines": booking_service.describe_bookings(db, items),
        "pager": make_pager(page, BOOKINGS_PER_PAGE, total),
        "tab": tab.value,
    }
    return render(request, "bookings/list.html", context)


def _render_detail(
    request: Request,
    db: DbSession,
    user: User,
    now: datetime,
    booking_id: int,
    *,
    problem: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    booking = booking_service.get_own_booking(db, user, booking_id)
    (line,) = booking_service.describe_bookings(db, [booking])
    settings = get_business_settings(db)
    history = [
        describe_event(event, actor, user)
        for event, actor in booking_service.list_history(db, user, booking.id)
    ]

    # Why there is no Cancel button, when there is not one. Only live bookings
    # (pending, confirmed) can be cancelled at all, so a finished one says nothing.
    live = booking.status in (BookingStatus.PENDING, BookingStatus.CONFIRMED)
    cancellable = can_cancel(booking, user, now, settings)
    cancel_closed = None
    if live and not cancellable:
        cancel_closed = "started" if now >= booking.start_at else "cutoff"

    context = {
        "business": settings,
        "line": line,
        "history": history,
        "cancellable": cancellable,
        "cancel_closed": cancel_closed,
        "cutoff_at": cancellation_cutoff_at(booking.start_at, settings.cancellation_cutoff_hours),
        "problem": problem,
    }
    return render(request, "bookings/detail.html", context, status_code=status_code)


@router.get("/me/bookings/{booking_id}", response_class=HTMLResponse, name="my_booking")
def my_booking(
    request: Request, booking_id: int, db: DbSession, clock: ClockDep, user: CurrentUser
) -> HTMLResponse:
    """Raises: 404 `BOOKING_NOT_FOUND` for a missing booking or someone else's."""
    return _render_detail(request, db, user, clock.now(), booking_id)


@router.get("/me/bookings/{booking_id}/ics", name="my_booking_ics")
def my_booking_ics(booking_id: int, db: DbSession, user: CurrentUser) -> Response:
    """The booking as a `.ics` download ("Add to calendar").

    Raises: 404 `BOOKING_NOT_FOUND` for a missing booking or someone else's.
    """
    booking = booking_service.get_own_booking(db, user, booking_id)
    return Response(
        booking_ics(db, booking),
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="booking-{booking.id}.ics"'},
    )


@router.post("/me/bookings/{booking_id}/cancel", name="my_booking_cancel")
def cancel(
    request: Request, booking_id: int, db: DbSession, clock: ClockDep, user: CurrentUser
) -> Response:
    """Cancel and show the booking as cancelled.

    Raises: 404 `BOOKING_NOT_FOUND`. A 409 (`CANCELLATION_CUTOFF_PASSED`,
    `INVALID_TRANSITION`, `BOOKING_STATE_CHANGED`) is not an error page: the
    booking comes back as it now is, with the reason. Nothing else is caught.
    """
    now = clock.now()
    booking_service.get_own_booking(db, user, booking_id)
    try:
        booking_service.transition(db, user, booking_id, BookingStatus.CANCELLED, now)
    except AppError as error:
        if error.status_code != 409:
            raise
        return _render_detail(
            request, db, user, now, booking_id, problem=error.message, status_code=409
        )
    response = RedirectResponse(f"/me/bookings/{booking_id}", status_code=303)
    set_flash(response, "cancelled")
    return response
