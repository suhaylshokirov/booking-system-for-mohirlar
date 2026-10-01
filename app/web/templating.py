"""The Jinja2 environment and the one `render` helper every web route uses.

`render` adds what every page needs to the template context, so a route only
passes its own data:

- `csrf_token`: for the hidden field of every form on the page (including the
  header's "Sign out"). A visitor without the cookie yet gets one here, so a
  login or register form works on the first visit (see `app/api/csrf.py`).
- `current_user`: the signed-in user or `None`, as loaded by
  `app/web/deps.load_current_user`. Left out entirely when that dependency did
  not run (an error page for an unknown address): the header then shows
  neither "Sign in" nor the account menu rather than guess wrong.
- `flash`: a one-time notice ("You're signed out.") carried across a redirect.

Flash notices travel in a short-lived cookie that holds only a *key* into
`FLASH_MESSAGES`, never the text itself. The page can therefore only ever show
wording we wrote; a tampered cookie with an unknown key shows nothing. The
cookie is deleted by the response that displays it, so a notice appears once.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fastapi import Request, Response
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.api.cookies import CSRF_COOKIE, set_csrf_cookie
from app.core.config import get_settings
from app.core.security import generate_csrf_token
from app.schemas.provider import photo_url
from app.web import formatting

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["money"] = formatting.money
templates.env.filters["duration"] = formatting.duration
templates.env.filters["phone"] = formatting.phone
templates.env.filters["photo_url"] = photo_url
templates.env.filters["local_time"] = formatting.local_time
templates.env.filters["local_date"] = formatting.local_date
templates.env.filters["day_label"] = formatting.day_label
templates.env.filters["utc_offset"] = formatting.utc_offset
templates.env.filters["day_offset"] = formatting.day_offset

FLASH_COOKIE = "flash"


@dataclass(frozen=True)
class Notice:
    text: str
    kind: Literal["info", "success", "error"] = "info"


# Every notice a redirect can leave behind.
FLASH_MESSAGES: dict[str, Notice] = {
    "signed_in": Notice("You're signed in.", "success"),
    "signed_out": Notice("You're signed out."),
    "cancelled": Notice("Booking cancelled. That time is free again.", "success"),
    "booking_confirmed": Notice("Booking confirmed.", "success"),
    "booking_completed": Notice("Booking marked as completed.", "success"),
    "booking_cancelled_barber": Notice("Booking cancelled. That time is free again.", "success"),
    "service_saved": Notice("Service saved.", "success"),
    "service_activated": Notice("Service is active again.", "success"),
    "service_deactivated": Notice("Service deactivated. Existing bookings are kept.", "success"),
    "provider_saved": Notice("Provider saved.", "success"),
    "provider_activated": Notice("Provider is active again.", "success"),
    "provider_deactivated": Notice("Provider deactivated. Existing bookings are kept.", "success"),
    "rule_added": Notice("Working window added.", "success"),
    "rule_removed": Notice("Working window removed.", "success"),
    "exception_added": Notice("Exception added.", "success"),
    "exception_removed": Notice("Exception removed. The weekly hours apply again.", "success"),
    "settings_saved": Notice("Settings saved.", "success"),
    "booked": Notice(
        "Booking requested. It shows as pending until the business confirms it.", "success"
    ),
}


def set_flash(response: Response, key: str) -> None:
    """Queue the notice `key` for the next page this browser renders."""
    if key not in FLASH_MESSAGES:
        raise KeyError(f"Unknown flash message {key!r}; add it to FLASH_MESSAGES.")
    response.set_cookie(
        FLASH_COOKIE,
        key,
        max_age=60,  # long enough to survive the redirect, short enough to never linger
        httponly=True,
        samesite="lax",
        secure=get_settings().app_env == "production",
        path="/",
    )


def render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render `template` with the shared context, consuming any flash notice."""
    csrf_token = request.cookies.get(CSRF_COOKIE)
    new_csrf_token = csrf_token is None
    if new_csrf_token:
        csrf_token = generate_csrf_token()

    flash_key = request.cookies.get(FLASH_COOKIE)
    page_context: dict[str, Any] = {
        "csrf_token": csrf_token,
        "flash": FLASH_MESSAGES.get(flash_key or ""),
    }
    if hasattr(request.state, "current_user"):
        page_context["current_user"] = request.state.current_user
    page_context.update(context or {})

    response = templates.TemplateResponse(request, template, page_context, status_code=status_code)
    if new_csrf_token:
        set_csrf_cookie(response, csrf_token)
    if flash_key:
        response.delete_cookie(FLASH_COOKIE, path="/")
    return response
