"""Every booking, for the admin: a filterable list, one booking's detail, and the actions.

    GET  /admin/bookings                   table with filters and pages
    GET  /admin/bookings/{id}              the booking and its full history
    POST /admin/bookings/{id}/confirm      pending -> confirmed
    POST /admin/bookings/{id}/complete     confirmed -> completed (once it has ended)
    POST /admin/bookings/{id}/cancel       cancel; `reason` (required for a confirmed one)

Admin only (`WebAdmin`). Every action is `booking.transition`, the same code the
JSON API uses, so who may do what and when lives in `booking_state` only; the
buttons shown are a convenience and the server still decides. A refused action
(409, or 422 for a missing reason) shows the booking's page again with the
reason, never an error page.

The filters are a GET form, so a filtered list is a shareable address and works
without JavaScript. With JavaScript (`initLiveFilter`) a change fetches just the
table (`X-Requested-With`) and swaps it in. A filter value that makes no sense
(a date that is not a date, an unknown status) is ignored rather than refused:
the list simply is not narrowed by it.

Actions carry a hidden `next` (the page they were pressed on) so the admin lands
back there; `safe_next_path` keeps it on this site.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.core.errors import AppError
from app.models.booking import BookingEvent, BookingStatus
from app.models.user import User
from app.services import booking as booking_service
from app.services.booking_state import is_stale_pending
from app.services.business_settings import get_business_settings
from app.services.provider_catalog import list_providers
from app.web.admin import ALL_PROVIDERS, _render_dashboard
from app.web.deps import WebAdmin
from app.web.paging import MAX_PAGE, make_pager, page_params
from app.web.redirects import safe_next_path
from app.web.templating import render, set_flash

router = APIRouter(include_in_schema=False)

ClockDep = Annotated[Clock, Depends(get_clock)]

BOOKINGS_PER_PAGE = 20

_BOOKINGS_LIST = "/admin/bookings"


def _as_status(text: str) -> BookingStatus | None:
    try:
        return BookingStatus(text)
    except ValueError:
        return None


def _as_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _as_id(text: str) -> int | None:
    return int(text) if text.isdecimal() and len(text) < 10 else None


@dataclass(frozen=True)
class Row:
    line: booking_service.BookingLine
    customer: User
    is_stale: bool
    can_complete: bool


@router.get("/admin/bookings", response_class=HTMLResponse, name="admin_bookings")
def bookings_list(
    request: Request,
    db: DbSession,
    clock: ClockDep,
    admin: WebAdmin,
    status: str = "",
    provider: str = "",
    date_from: str = "",
    date_to: str = "",
    customer: str = "",
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
) -> HTMLResponse:
    """Raises: 404 for a page past the last. A fragment (the table only) for `X-Requested-With`."""
    now = clock.now()
    customer = customer.strip()
    items, total = booking_service.list_all_bookings(
        db,
        page_params(page, BOOKINGS_PER_PAGE),
        _as_status(status),
        _as_id(provider),
        None,
        _as_date(date_from),
        _as_date(date_to),
        customer or None,
    )
    customers = booking_service.customers_of(db, items)
    rows = [
        Row(
            line,
            customers[line.booking.customer_id],
            is_stale_pending(line.booking, now),
            now >= line.booking.end_at,
        )
        for line in booking_service.describe_bookings(db, items)
    ]
    filters = {
        "status": status,
        "provider": provider,
        "date_from": date_from,
        "date_to": date_to,
        "customer": customer,
    }
    kept = urlencode({key: value for key, value in filters.items() if value})
    context = {
        "business": get_business_settings(db),
        "rows": rows,
        "pager": make_pager(page, BOOKINGS_PER_PAGE, total),
        "total": total,
        "filters": filters,
        "keep": kept + "&" if kept else "",
        "statuses": list(BookingStatus),
        "providers": [
            view.provider
            for view in list_providers(db, ALL_PROVIDERS, include_inactive=True, service_id=None)[0]
        ],
        "next": request.url.path + (f"?{request.url.query}" if request.url.query else ""),
    }
    template = (
        "_partials/admin_bookings_table.html"
        if request.headers.get("x-requested-with")
        else "admin/bookings.html"
    )
    return render(request, template, context)


@dataclass(frozen=True)
class HistoryEntry:
    at: datetime
    text: str
    reason: str | None


def _describe(event: BookingEvent, actor: User | None) -> HistoryEntry:
    who = "the system" if actor is None else actor.full_name
    if event.from_status is None:
        text = f"Requested (by {who})"
    else:
        text = f"{event.from_status.value.capitalize()} → {event.to_status.value} by {who}"
    return HistoryEntry(event.created_at, text, event.reason)


def _render_detail(
    request: Request,
    db: DbSession,
    admin: User,
    now: datetime,
    booking_id: int,
    *,
    problem: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    booking = booking_service.get_booking(db, admin, booking_id)
    (line,) = booking_service.describe_bookings(db, [booking])
    context = {
        "business": get_business_settings(db),
        "line": line,
        "customer": booking_service.customers_of(db, [booking])[booking.customer_id],
        "is_stale": is_stale_pending(booking, now),
        "can_complete": now >= booking.end_at,
        "history": [
            _describe(event, actor)
            for event, actor in booking_service.list_history(db, admin, booking.id)
        ],
        "problem": problem,
        "next": f"{_BOOKINGS_LIST}/{booking.id}",
    }
    return render(request, "admin/booking_detail.html", context, status_code=status_code)


@router.get("/admin/bookings/{booking_id}", response_class=HTMLResponse, name="admin_booking")
def booking_detail(
    request: Request, booking_id: int, db: DbSession, clock: ClockDep, admin: WebAdmin
) -> HTMLResponse:
    """Raises: 404 `BOOKING_NOT_FOUND`."""
    return _render_detail(request, db, admin, clock.now(), booking_id)


def _act(
    request: Request,
    db: DbSession,
    clock: Clock,
    admin: User,
    booking_id: int,
    to: BookingStatus,
    flash: str,
    next_path: str,
    reason: str | None = None,
) -> Response:
    now = clock.now()
    # Where the admin was: the dashboard shows the refusal itself, every other
    # page sends them to the booking, where the reason reads best.
    next_path = safe_next_path(next_path) if next_path else "/admin"
    try:
        booking_service.transition(db, admin, booking_id, to, now, reason)
    except AppError as error:
        if error.status_code not in (409, 422):
            raise
        if next_path == "/admin":
            return _render_dashboard(
                request, db, now, problem=error.message, status_code=error.status_code
            )
        return _render_detail(
            request,
            db,
            admin,
            now,
            booking_id,
            problem=error.message,
            status_code=error.status_code,
        )
    response = RedirectResponse(next_path, status_code=303)
    set_flash(response, flash)
    return response


@router.post("/admin/bookings/{booking_id}/confirm", name="admin_booking_confirm")
def confirm(
    request: Request,
    booking_id: int,
    db: DbSession,
    clock: ClockDep,
    admin: WebAdmin,
    next: Annotated[str, Form()] = "",
) -> Response:
    """Raises: 404 `BOOKING_NOT_FOUND`; refusals are shown as a notice (409)."""
    return _act(
        request, db, clock, admin, booking_id, BookingStatus.CONFIRMED, "booking_confirmed", next
    )


@router.post("/admin/bookings/{booking_id}/complete", name="admin_booking_complete")
def complete(
    request: Request,
    booking_id: int,
    db: DbSession,
    clock: ClockDep,
    admin: WebAdmin,
    next: Annotated[str, Form()] = "",
) -> Response:
    """Raises: 404 `BOOKING_NOT_FOUND`; refusals (`TOO_EARLY_TO_COMPLETE`) are shown as a notice."""
    return _act(
        request, db, clock, admin, booking_id, BookingStatus.COMPLETED, "booking_completed", next
    )


@router.post("/admin/bookings/{booking_id}/cancel", name="admin_booking_cancel")
def cancel(
    request: Request,
    booking_id: int,
    db: DbSession,
    clock: ClockDep,
    admin: WebAdmin,
    reason: Annotated[str, Form(max_length=500)] = "",
    next: Annotated[str, Form()] = "",
) -> Response:
    """Raises: 404 `BOOKING_NOT_FOUND`; refusals are shown as a notice (409/422)."""
    return _act(
        request,
        db,
        clock,
        admin,
        booking_id,
        BookingStatus.CANCELLED,
        "booking_cancelled_admin",
        next,
        reason.strip() or None,
    )
