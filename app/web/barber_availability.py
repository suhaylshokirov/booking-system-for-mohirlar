"""A barber's own working hours: weekly rules and one-off exceptions.

    GET  /barber/hours                           the editor
    POST /barber/hours/rules                     add a weekly window
    POST /barber/hours/rules/{rid}/delete        remove it
    POST /barber/hours/exceptions                close a date / give it custom hours
    POST /barber/hours/exceptions/{eid}/delete

Barber only (`WebBarber`), and only their own hours: the provider comes from the
signed-in barber (`user.provider_id`), never from the address, so there is no way
to open or change another barber's hours from here. Same schemas and
`services/availability` functions as
the JSON API, so the rules (slot grid, no overlap on a weekday, no exception in
the past) exist once. A refused write (422 or 409) shows the editor again with
the service's message and what was typed kept.

Editing hours never touches bookings. Every time the editor is drawn it lists
the future bookings that no longer fit (`find_conflicts`), so the barber sees
the damage of a change, and of an earlier one, and can contact those customers
or cancel the bookings from the bookings list.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.core.errors import AppError
from app.core.timezones import utc_to_local
from app.schemas.availability import ExceptionCreate, RuleCreate
from app.services import availability, provider_catalog
from app.services.booking import describe_bookings
from app.services.business_settings import get_business_settings
from app.web.deps import WebBarber
from app.web.templating import render, set_flash

router = APIRouter(include_in_schema=False)

ClockDep = Annotated[Clock, Depends(get_clock)]

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

CONFLICT_REASONS = {
    "day_off": "that date is closed",
    "no_hours": "no hours are set for that weekday",
    "outside_hours": "it is outside the working hours",
}

_BAD_INPUT = (
    "Check the form: pick the weekday or date, "
    "and give times like 09:00 (the end later than the start)."
)


def _render_editor(
    request: Request,
    db: DbSession,
    now: datetime,
    provider_id: int,
    *,
    problem: str | None = None,
    rule_values: dict | None = None,
    exception_values: dict | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    view = provider_catalog.get_provider(db, provider_id, include_inactive=True)
    settings = get_business_settings(db)
    rules = availability.list_rules(db, provider_id, include_inactive=True)
    conflicts = availability.find_conflicts(db, provider_id, now)
    lines = describe_bookings(db, [c.booking for c in conflicts])
    context = {
        "business": settings,
        "provider": view.provider,
        "week": [
            (index, name, [r for r in rules if r.weekday == index])
            for index, name in enumerate(WEEKDAYS)
        ],
        "exceptions": availability.list_exceptions(db, provider_id),
        "today": utc_to_local(now, settings.timezone).date(),
        "conflicts": [
            (line, CONFLICT_REASONS[c.reason]) for line, c in zip(lines, conflicts, strict=True)
        ],
        "problem": problem,
        "rule_values": rule_values or {},
        "exception_values": exception_values or {},
        "step": settings.slot_granularity_minutes * 60,
    }
    return render(request, "barber/availability.html", context, status_code=status_code)


def _done(flash: str) -> Response:
    response = RedirectResponse("/barber/hours", status_code=303)
    set_flash(response, flash)
    return response


@router.get("/barber/hours", response_class=HTMLResponse, name="barber_availability")
def editor(request: Request, db: DbSession, clock: ClockDep, barber: WebBarber) -> HTMLResponse:
    return _render_editor(request, db, clock.now(), barber.provider_id)


@router.post("/barber/hours/rules", name="barber_rule_create")
def add_rule(
    request: Request,
    db: DbSession,
    clock: ClockDep,
    barber: WebBarber,
    weekday: Annotated[str, Form()] = "",
    start_time: Annotated[str, Form()] = "",
    end_time: Annotated[str, Form()] = "",
) -> Response:
    """Raises: nothing; a refused window is shown again (422, or 409 for an overlap)."""
    provider_id = barber.provider_id
    values = {"weekday": weekday, "start_time": start_time, "end_time": end_time}

    def again(problem: str, status_code: int) -> Response:
        return _render_editor(
            request,
            db,
            clock.now(),
            provider_id,
            problem=problem,
            rule_values=values,
            status_code=status_code,
        )

    try:
        body = RuleCreate(weekday=weekday, start_time=start_time, end_time=end_time)
    except ValidationError:
        return again(_BAD_INPUT, 422)
    try:
        availability.create_rule(db, provider_id, body.model_dump())
    except AppError as error:
        if error.status_code not in (409, 422):
            raise
        return again(error.message, error.status_code)
    return _done("rule_added")


@router.post("/barber/hours/rules/{rule_id}/delete", name="barber_rule_delete")
def remove_rule(rule_id: int, db: DbSession, barber: WebBarber) -> Response:
    """Raises: 404 `NOT_FOUND` (no such rule among the barber's own)."""
    availability.delete_rule(db, barber.provider_id, rule_id)
    return _done("rule_removed")


@router.post("/barber/hours/exceptions", name="barber_exception_create")
def add_exception(
    request: Request,
    db: DbSession,
    clock: ClockDep,
    barber: WebBarber,
    date: Annotated[str, Form()] = "",
    start_time: Annotated[str, Form()] = "",
    end_time: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
) -> Response:
    """No times means a day off.

    Raises: nothing; a refused exception is shown again (422, or 409 when the
    date already has one).
    """
    provider_id = barber.provider_id
    values = {"date": date, "start_time": start_time, "end_time": end_time, "reason": reason}

    def again(problem: str, status_code: int) -> Response:
        return _render_editor(
            request,
            db,
            clock.now(),
            provider_id,
            problem=problem,
            exception_values=values,
            status_code=status_code,
        )

    try:
        body = ExceptionCreate(
            date=date,
            # An empty time box means "not given", which makes the date a day off.
            start_time=start_time or None,
            end_time=end_time or None,
            reason=reason,
        )
    except ValidationError:
        return again(_BAD_INPUT, 422)
    try:
        availability.create_exception(db, provider_id, body.model_dump(), clock)
    except AppError as error:
        if error.status_code not in (409, 422):
            raise
        return again(error.message, error.status_code)
    return _done("exception_added")


@router.post("/barber/hours/exceptions/{exception_id}/delete", name="barber_exception_delete")
def remove_exception(exception_id: int, db: DbSession, barber: WebBarber) -> Response:
    """Raises: 404 `NOT_FOUND` (no such exception among the barber's own)."""
    availability.delete_exception(db, barber.provider_id, exception_id)
    return _done("exception_removed")
