"""Booking in the browser: pick a time, confirm it, done.

    GET  /book/{service_id}           the picker: who (a person or "anyone"),
                                      which day, then the free times as tiles
    GET  /book/{service_id}/confirm   what you're about to book (signed in)
    POST /book/{service_id}           book it: `services/booking.create_booking`

Everything that decides is a service: the free times come from
`slot_query.get_slots`, the booking from `booking.create_booking`, which the
database backs with its exclusion constraints (ADR 0001). The times shown are
advisory, so the answer to losing a race is not an error page: the picker
comes back for the same day, freshly computed, with "That time was just
taken — pick another."

Live picker: when app.js changes the person or day it asks for the same URL
with `X-Requested-With: XMLHttpRequest` and gets only
`_partials/slot_grid.html`, which it swaps in. Without JS the same GET form
returns the whole page, so the flow works either way.

A slot is submitted as one radio value, `"<provider id>|<UTC start>"`, because
with "anyone" the tiles of several people sit in one group.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.api.deps import CurrentUser
from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.core.errors import AppError
from app.core.pagination import MAX_LIMIT, PageParams
from app.core.timezones import utc_to_local
from app.models.provider import Provider
from app.schemas.booking import BookingCreate
from app.services.booking import create_booking
from app.services.booking_state import cancellation_cutoff_at
from app.services.business_settings import get_business_settings
from app.services.provider_catalog import get_provider, list_providers
from app.services.service_catalog import get_service
from app.services.slot_query import ProviderSlots, bookable_dates, get_slots
from app.web.forms import field_errors
from app.web.templating import render, set_flash

router = APIRouter(include_in_schema=False)

ClockDep = Annotated[Clock, Depends(get_clock)]

ANYONE = "any"
PARTIAL_HEADER = "X-Requested-With"

SLOT_TAKEN_MESSAGE = "That time was just taken — pick another."

# Where a day is split for reading: before 12:00, before 17:00, the rest.
_DAY_PARTS = (("Morning", 12), ("Afternoon", 17), ("Evening", 24))


@dataclass(frozen=True)
class SlotChoice:
    start: datetime  # UTC
    value: str  # what the radio submits


@dataclass(frozen=True)
class ProviderDay:
    """One person's free times for the day, split into morning/afternoon/evening."""

    provider: Provider
    parts: list[tuple[str, list[SlotChoice]]]

    @property
    def count(self) -> int:
        return sum(len(choices) for _, choices in self.parts)


def slot_value(provider_id: int, start: datetime) -> str:
    return f"{provider_id}|{start.isoformat()}"


def parse_slot(value: str) -> tuple[int, datetime]:
    """Undo `slot_value`.

    Raises:
        AppError: 422 `INVALID_SLOT` for anything `slot_value` did not make,
            including a start without a UTC offset.
    """
    provider_part, _, start_part = value.partition("|")
    try:
        provider_id = int(provider_part)
        start = datetime.fromisoformat(start_part)
    except ValueError:
        start = None
    if start is None or start.tzinfo is None:
        raise AppError("INVALID_SLOT", "Pick a time from the list.", status_code=422)
    return provider_id, start


def parse_provider_filter(value: str | None) -> int | None:
    """ "any" (or nothing) -> None; a provider id -> that id.

    Raises:
        AppError: 422 `INVALID_PROVIDER` for anything else.
    """
    if value in (None, "", ANYONE):
        return None
    try:
        return int(value)
    except ValueError:
        raise AppError("INVALID_PROVIDER", "Pick someone from the list.", status_code=422) from None


def day_parts(item: ProviderSlots, timezone: str) -> ProviderDay:
    """Group one provider's free starts by the part of the (local) day."""
    parts: list[tuple[str, list[SlotChoice]]] = []
    starts = list(item.starts)
    for label, before_hour in _DAY_PARTS:
        choices = []
        while starts and utc_to_local(starts[0], timezone).hour < before_hour:
            start = starts.pop(0)
            choices.append(SlotChoice(start, slot_value(item.provider.id, start)))
        if choices:
            parts.append((label, choices))
    return ProviderDay(item.provider, parts)


def _render_picker(
    request: Request,
    db: DbSession,
    now: datetime,
    service_id: int,
    provider_filter: str | None,
    day: date | None,
    *,
    problem: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """The picker page, or only its slot grid for the live picker.

    A day outside the bookable range is not an error page: the picker says
    which dates can be booked. Everything else `get_slots` raises (unknown
    service or person) is.
    """
    service = get_service(db, service_id, include_inactive=False)
    settings = get_business_settings(db)
    provider_id = parse_provider_filter(provider_filter)
    first_day, last_day = bookable_dates(settings, now)
    day = day or first_day

    groups: list[ProviderDay] = []
    try:
        result = get_slots(db, service.id, day, provider_id, now)
        groups = [day_parts(item, settings.timezone) for item in result.providers]
    except AppError as error:
        if error.code != "DATE_OUT_OF_RANGE":
            raise
        problem = error.message
        status_code = 422

    staff, _ = list_providers(
        db, PageParams(limit=MAX_LIMIT, offset=0), include_inactive=False, service_id=service.id
    )
    one_day = timedelta(days=1)
    context = {
        "service": service,
        "business": settings,
        "staff": [view.provider for view in staff],
        "provider_filter": str(provider_id) if provider_id else ANYONE,
        "day": day,
        "first_day": first_day,
        "last_day": last_day,
        "prev_day": day - one_day if first_day < day <= last_day else None,
        "next_day": day + one_day if first_day <= day < last_day else None,
        "groups": groups,
        "total_free": sum(group.count for group in groups),
        "problem": problem,
    }
    partial = request.headers.get(PARTIAL_HEADER) == "XMLHttpRequest"
    template = "_partials/slot_grid.html" if partial else "booking/pick.html"
    response = render(request, template, context, status_code=status_code)
    # The same URL answers with a fragment or a page: caches must keep both.
    response.headers["Vary"] = PARTIAL_HEADER
    return response


@router.get("/book/{service_id}", response_class=HTMLResponse, name="book")
def pick_time(
    request: Request,
    service_id: int,
    db: DbSession,
    clock: ClockDep,
    provider: str | None = None,
    day: Annotated[date | None, Query(alias="date")] = None,
) -> HTMLResponse:
    """Raises: 404 for an unknown or retired service or person; 422 for a
    person who does not do this service or a malformed filter."""
    return _render_picker(request, db, clock.now(), service_id, provider, day)


def _confirm_context(db: DbSession, service_id: int, provider_id: int, start: datetime) -> dict:
    service = get_service(db, service_id, include_inactive=False)
    person = get_provider(db, provider_id, include_inactive=False).provider
    settings = get_business_settings(db)
    return {
        "service": service,
        "person": person,
        "business": settings,
        "start": start,
        "end": start + timedelta(minutes=service.duration_minutes),
        "day": utc_to_local(start, settings.timezone).date(),  # for "Pick another time"
        "cutoff_at": cancellation_cutoff_at(start, settings.cancellation_cutoff_hours),
    }


def _still_free(db: DbSession, service_id: int, provider_id: int, start: datetime, now) -> bool:
    """Is `start` still among the provider's free times? Advisory, like the grid."""
    settings = get_business_settings(db)
    day = utc_to_local(start, settings.timezone).date()
    result = get_slots(db, service_id, day, provider_id, now)
    return start in result.providers[0].starts


@router.get("/book/{service_id}/confirm", response_class=HTMLResponse, name="book_confirm")
def confirm_page(
    request: Request,
    service_id: int,
    db: DbSession,
    clock: ClockDep,
    user: CurrentUser,
    slot: str = "",
    provider: str | None = None,
) -> HTMLResponse:
    """Needs a signed-in customer: a visitor is sent to log in and back here
    (the 401 redirect in `app/web/errors.py`), with the chosen time kept."""
    now = clock.now()
    if not slot:
        return _render_picker(
            request,
            db,
            now,
            service_id,
            provider,
            None,
            problem="Pick a time first.",
            status_code=422,
        )
    provider_id, start = parse_slot(slot)
    settings = get_business_settings(db)
    day = utc_to_local(start, settings.timezone).date()
    try:
        free = _still_free(db, service_id, provider_id, start, now)
    except AppError as error:
        if error.status_code != 422:
            raise
        free = False
    if not free:
        return _render_picker(
            request,
            db,
            now,
            service_id,
            provider,
            day,
            problem="That time is no longer free — pick another.",
            status_code=409,
        )

    context = _confirm_context(db, service_id, provider_id, start)
    context.update({"slot": slot, "provider_filter": provider or ANYONE, "notes": "", "errors": {}})
    return render(request, "booking/confirm.html", context)


@router.post("/book/{service_id}", name="book_create")
def book(
    request: Request,
    service_id: int,
    db: DbSession,
    clock: ClockDep,
    user: CurrentUser,
    slot: Annotated[str, Form()] = "",
    provider: Annotated[str, Form()] = ANYONE,
    notes: Annotated[str, Form()] = "",
) -> Response:
    """Create the booking and go to it; a lost race returns to the picker.

    409 `SLOT_TAKEN` / `CUSTOMER_OVERLAP` and the 422 booking rules (for
    example the lead time ran out while the page was open) re-render the
    picker for that day with the reason and the status code. Nothing else is
    caught.
    """
    now = clock.now()
    if not slot:
        return _render_picker(
            request,
            db,
            now,
            service_id,
            provider,
            None,
            problem="Pick a time first.",
            status_code=422,
        )
    provider_id, start = parse_slot(slot)
    try:
        body = BookingCreate(
            service_id=service_id, provider_id=provider_id, start_at=start, notes=notes
        )
    except ValidationError as error:
        context = _confirm_context(db, service_id, provider_id, start)
        errors = field_errors(error, {"notes": "Keep the note under 500 characters."})
        context.update(
            {"slot": slot, "provider_filter": provider, "notes": notes, "errors": errors}
        )
        return render(request, "booking/confirm.html", context, status_code=422)

    try:
        booking = create_booking(
            db, user, body.service_id, body.provider_id, body.start_at, body.notes, now
        )
    except AppError as error:
        if error.status_code not in (409, 422):
            raise
        settings = get_business_settings(db)
        day = utc_to_local(start, settings.timezone).date()
        message = SLOT_TAKEN_MESSAGE if error.code == "SLOT_TAKEN" else error.message
        return _render_picker(
            request,
            db,
            now,
            service_id,
            provider,
            day,
            problem=message,
            status_code=error.status_code,
        )

    response = RedirectResponse(f"/me/bookings/{booking.id}", status_code=303)
    set_flash(response, "booked")
    return response
