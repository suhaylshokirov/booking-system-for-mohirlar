"""A barber's own profile: photo, name, bio, phone, offered services, and whether
customers see them.

    GET  /barber/profile               the form and the visibility switch
    POST /barber/profile               save photo, name, bio, phone and offered services
    POST /barber/profile/activate      show me to customers again (and /deactivate)

Barber only (`WebBarber`), and only the barber's own provider record: it comes from
the signed-in user (`user.provider_id`), never from the address, so one barber
cannot open or change another's profile from here. Providers are not created here;
a barber account is created together with its provider (`scripts/create_barber.py`).

Same schema (`ProviderUpdate`) and service functions as `/api/v1/providers`. The
offered services are checkboxes on the same form as the name, saved together:
`replace_offered_services` replaces the whole set, which is exactly what a set of
checkboxes posts. Only active services are offered as choices (a deactivated one
cannot be offered, see `provider_catalog`).

The form is `multipart/form-data` because it can carry the photo; the photo rules
(type judged by content, 2 MB) are `services/provider_photo`'s, as for the API.

A problem re-renders the form (422) with what was typed kept (a chosen file cannot
be kept: browsers never pre-fill a file input). The profile, its services and the
photo are saved in one savepoint, so if the services or the photo are refused the
whole save is rolled back rather than half-applied.
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.core.db import DbSession
from app.core.errors import AppError
from app.core.pagination import PageParams
from app.schemas.provider import ProviderUpdate
from app.services import provider_catalog, provider_photo, service_catalog
from app.services.business_settings import get_business_settings
from app.web import formatting
from app.web.deps import WebBarber
from app.web.forms import field_errors
from app.web.templating import render, set_flash

router = APIRouter(include_in_schema=False)

# A business has a handful of services; the form lists them all.
ALL = PageParams(limit=200, offset=0)

_MESSAGES = {
    "name": "Enter a name, up to 100 characters.",
    "bio": "Keep the bio under 1000 characters.",
    "phone": "Enter the number with its country code, such as +998 90 123 45 67.",
}
_SERVICES_GONE = "One of the chosen services is no longer active. Check the list and save again."


def _form(request, db, view, values, errors=None, status_code=200):
    services, _ = service_catalog.list_services(db, ALL, include_inactive=False)
    context = {
        "business": get_business_settings(db),
        "provider": view.provider,
        "values": values,
        "errors": errors or {},
        "choices": services,
    }
    return render(request, "barber/profile.html", context, status_code=status_code)


def _values(view) -> dict:
    return {
        "name": view.provider.name,
        "bio": view.provider.bio or "",
        # Shown grouped (+998 90 123 45 67); the spaces are dropped again on save.
        "phone": formatting.phone(view.provider.phone) if view.provider.phone else "",
        "service_ids": [s.id for s in view.services],
    }


def _save(
    db: DbSession,
    provider_id: int,
    fields: dict[str, str],
    service_ids: list[int],
    photo: bytes | None,
    remove_photo: bool,
) -> dict[str, str]:
    """Returns the field errors (empty on success); on errors nothing has been changed.

    `photo` is a newly chosen file (None if none was chosen); it wins over
    `remove_photo` when both are sent.
    """
    try:
        body = ProviderUpdate(**fields)
    except ValidationError as error:
        return field_errors(error, _MESSAGES)
    try:
        # A savepoint: if the services or the photo are refused, the profile
        # written just before them is undone too, and nothing else in the
        # request is.
        with db.begin_nested():
            provider_catalog.update_provider(db, provider_id, body.model_dump(exclude_unset=True))
            provider_catalog.replace_offered_services(db, provider_id, service_ids)
            if photo is not None:
                provider_photo.set_photo(db, provider_id, photo)
            elif remove_photo:
                provider_photo.remove_photo(db, provider_id)
    except AppError as error:
        if error.code == "UNKNOWN_SERVICE":
            return {"service_ids": _SERVICES_GONE}
        if error.code in ("PHOTO_TOO_LARGE", "UNSUPPORTED_PHOTO"):
            return {"photo": error.message}
        raise
    return {}


@router.get("/barber/profile", response_class=HTMLResponse, name="barber_profile")
def edit_form(request: Request, db: DbSession, barber: WebBarber) -> HTMLResponse:
    view = provider_catalog.get_provider(db, barber.provider_id, include_inactive=True)
    return _form(request, db, view, _values(view))


@router.post("/barber/profile", name="barber_profile_update")
def update(
    request: Request,
    db: DbSession,
    barber: WebBarber,
    name: Annotated[str, Form()] = "",
    bio: Annotated[str, Form()] = "",
    phone: Annotated[str, Form()] = "",
    service_ids: Annotated[list[int], Form()] = [],  # noqa: B006 - FastAPI copies the default
    photo: Annotated[UploadFile | None, File()] = None,
    remove_photo: Annotated[bool, Form()] = False,
) -> Response:
    """Raises: nothing; a bad form is shown again (422)."""
    view = provider_catalog.get_provider(db, barber.provider_id, include_inactive=True)
    # A browser sends an empty, unnamed file part when no file was chosen.
    chosen = photo is not None and bool(photo.filename)
    data = provider_photo.read_upload(photo.file) if chosen else None
    fields = {"name": name, "bio": bio, "phone": phone}
    errors = _save(db, barber.provider_id, fields, service_ids, data, remove_photo)
    if errors:
        values = {"name": name, "bio": bio, "phone": phone, "service_ids": service_ids}
        return _form(request, db, view, values, errors, 422)
    response = RedirectResponse("/barber/profile", status_code=303)
    set_flash(response, "provider_saved")
    return response


@router.post("/barber/profile/activate", name="barber_profile_activate")
def activate(db: DbSession, barber: WebBarber) -> Response:
    provider_catalog.set_provider_active(db, barber.provider_id, active=True)
    response = RedirectResponse("/barber/profile", status_code=303)
    set_flash(response, "provider_activated")
    return response


@router.post("/barber/profile/deactivate", name="barber_profile_deactivate")
def deactivate(db: DbSession, barber: WebBarber) -> Response:
    provider_catalog.set_provider_active(db, barber.provider_id, active=False)
    response = RedirectResponse("/barber/profile", status_code=303)
    set_flash(response, "provider_deactivated")
    return response
