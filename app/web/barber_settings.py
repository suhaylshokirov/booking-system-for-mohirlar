"""The business settings in the barber area: name, timezone, currency and booking rules.

    GET  /barber/settings     the form, filled with the current values
    POST /barber/settings     save them all

Barber only (`WebBarber`). Validation is `SettingsUpdate`, the API's schema, and
the save is `business_settings.update_business_settings`, so a rule exists once.
A problem re-renders the form (422, or 409 for a granularity that active
services do not fit) with a message beside the field and what was typed kept.

The numbers are posted as text; `whole_number` turns them into ints (the
schema is strict about what a number is) and leaves anything else for the schema
to refuse. Saving never touches existing bookings: they are stored as UTC
instants with their own price and duration.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.core.db import DbSession
from app.core.errors import AppError
from app.schemas.business_settings import SettingsUpdate
from app.services.business_settings import get_business_settings, update_business_settings
from app.web.deps import WebBarber
from app.web.forms import field_errors, whole_number
from app.web.templating import render, set_flash

router = APIRouter(include_in_schema=False)

GRANULARITIES = [5, 10, 15, 20, 30, 60]

_MESSAGES = {
    "name": "Enter the business name, up to 100 characters.",
    "timezone": "Enter a timezone name such as Asia/Tashkent.",
    "currency": "Use the three capital letters of the currency code, such as UZS.",
    "slot_granularity_minutes": "Pick one of the listed slot sizes.",
    "min_lead_time_minutes": "Enter whole minutes, from 0 to 10080 (a week).",
    "max_booking_horizon_days": "Enter whole days, from 1 to 365.",
    "cancellation_cutoff_hours": "Enter whole hours, from 0 to 720.",
}

_NUMBERS = (
    "slot_granularity_minutes",
    "min_lead_time_minutes",
    "max_booking_horizon_days",
    "cancellation_cutoff_hours",
)

_FIELDS = ("name", "timezone", "currency", *_NUMBERS)


def _form(request: Request, db: DbSession, values: dict[str, Any], errors=None, status_code=200):
    context = {
        "business": get_business_settings(db),
        "values": values,
        "errors": errors or {},
        "granularities": GRANULARITIES,
    }
    return render(request, "barber/settings.html", context, status_code=status_code)


@router.get("/barber/settings", response_class=HTMLResponse, name="barber_settings")
def settings_form(request: Request, db: DbSession, barber: WebBarber) -> HTMLResponse:
    current = get_business_settings(db)
    return _form(request, db, {field: getattr(current, field) for field in _FIELDS})


@router.post("/barber/settings", name="barber_settings_save")
def settings_save(
    request: Request,
    db: DbSession,
    barber: WebBarber,
    name: Annotated[str, Form()] = "",
    timezone: Annotated[str, Form()] = "",
    currency: Annotated[str, Form()] = "",
    slot_granularity_minutes: Annotated[str, Form()] = "",
    min_lead_time_minutes: Annotated[str, Form()] = "",
    max_booking_horizon_days: Annotated[str, Form()] = "",
    cancellation_cutoff_hours: Annotated[str, Form()] = "",
) -> Response:
    """Raises: nothing; a refused form (422 or 409) is shown again."""
    values = {
        "name": name,
        "timezone": timezone,
        "currency": currency.strip().upper(),
        "slot_granularity_minutes": slot_granularity_minutes,
        "min_lead_time_minutes": min_lead_time_minutes,
        "max_booking_horizon_days": max_booking_horizon_days,
        "cancellation_cutoff_hours": cancellation_cutoff_hours,
    }
    typed = {
        key: whole_number(value) if key in _NUMBERS else value.strip()
        for key, value in values.items()
    }
    try:
        changes = SettingsUpdate(**typed).model_dump(exclude_unset=True)
    except ValidationError as error:
        return _form(request, db, values, field_errors(error, _MESSAGES), 422)

    try:
        update_business_settings(db, changes)
    except AppError as error:
        if error.code == "INVALID_TIMEZONE":
            return _form(request, db, values, {"timezone": error.message}, 422)
        if error.code == "GRANULARITY_CONFLICT":
            names = ", ".join(s["name"] for s in error.details["services"])
            message = f"{error.message} Affected: {names}."
            return _form(request, db, values, {"slot_granularity_minutes": message}, 409)
        raise
    response = RedirectResponse("/barber/settings", status_code=303)
    set_flash(response, "settings_saved")
    return response
