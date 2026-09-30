"""A provider's working hours in the admin area: weekly rules and one-off exceptions.

    GET  /admin/providers/{id}/availability                      the editor
    POST /admin/providers/{id}/availability/rules                add a weekly window
    POST /admin/providers/{id}/availability/rules/{rid}/delete   remove it
    POST /admin/providers/{id}/availability/exceptions           close a date / give it custom hours
    POST /admin/providers/{id}/availability/exceptions/{eid}/delete

Admin only (`WebAdmin`). Same schemas and `services/availability` functions as
the JSON API, so the rules (slot grid, no overlap on a weekday, no exception in
the past) exist once. A refused write (422 or 409) shows the editor again with
the service's message and what was typed kept.

Editing hours never touches bookings. Every time the editor is drawn it lists
the future bookings that no longer fit (`find_conflicts`), so the admin sees
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
from app.web.deps import WebAdmin
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
    return render(request, "admin/availability.html", context, status_code=status_code)


def _done(provider_id: int, flash: str) -> Response:
    response = RedirectResponse(f"/admin/providers/{provider_id}/availability", status_code=303)
    set_flash(response, flash)
    return response


@router.get(
    "/admin/providers/{provider_id}/availability",
    response_class=HTMLResponse,
    name="admin_availability",
)
def editor(
    request: Request, provider_id: int, db: DbSession, clock: ClockDep, admin: WebAdmin
) -> HTMLResponse:
    """Raises: 404 `NOT_FOUND`."""
    return _render_editor(request, db, clock.now(), provider_id)


@router.post("/admin/providers/{provider_id}/availability/rules", name="admin_rule_create")
def add_rule(
    request: Request,
    provider_id: int,
    db: DbSession,
    clock: ClockDep,
    admin: WebAdmin,
    weekday: Annotated[str, Form()] = "",
    start_time: Annotated[str, Form()] = "",
    end_time: Annotated[str, Form()] = "",
) -> Response:
    """Raises: 404 `NOT_FOUND`; a refused window is shown again (422, or 409 for an overlap)."""
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
    return _done(provider_id, "rule_added")


@router.post(
    "/admin/providers/{provider_id}/availability/rules/{rule_id}/delete", name="admin_rule_delete"
)
def remove_rule(provider_id: int, rule_id: int, db: DbSession, admin: WebAdmin) -> Response:
    """Raises: 404 `NOT_FOUND`."""
    availability.delete_rule(db, provider_id, rule_id)
    return _done(provider_id, "rule_removed")


@router.post(
    "/admin/providers/{provider_id}/availability/exceptions", name="admin_exception_create"
)
def add_exception(
    request: Request,
    provider_id: int,
    db: DbSession,
    clock: ClockDep,
    admin: WebAdmin,
    date: Annotated[str, Form()] = "",
    start_time: Annotated[str, Form()] = "",
    end_time: Annotated[str, Form()] = "",
    reason: Annotated[str, Form()] = "",
) -> Response:
    """No times means a day off.

    Raises: 404 `NOT_FOUND`; a refused exception is shown again (422, or 409 when the
    date already has one).
    """
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
    return _done(provider_id, "exception_added")


@router.post(
    "/admin/providers/{provider_id}/availability/exceptions/{exception_id}/delete",
    name="admin_exception_delete",
)
def remove_exception(
    provider_id: int, exception_id: int, db: DbSession, admin: WebAdmin
) -> Response:
    """Raises: 404 `NOT_FOUND`."""
    availability.delete_exception(db, provider_id, exception_id)
    return _done(provider_id, "exception_removed")
