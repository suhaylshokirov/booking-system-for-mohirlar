"""Providers (staff) in the admin area: list, create, edit, offered services, activate.

    GET  /admin/providers                   every provider, inactive ones included
    GET  /admin/providers/new               blank form
    POST /admin/providers                   create
    GET  /admin/providers/{id}/edit         form filled in
    POST /admin/providers/{id}              save name, bio and offered services
    POST /admin/providers/{id}/activate     (and /deactivate)

Admin only (`WebAdmin`). Same schemas and service functions as
`/api/v1/providers`. The offered services are checkboxes on the same form as the
name, saved together: `replace_offered_services` replaces the whole set, which
is exactly what a set of checkboxes posts. Only active services are offered as
choices (a deactivated one cannot be offered, see `provider_catalog`).

A problem re-renders the form (422) with what was typed kept. The provider is
saved first and its services second, in one transaction, so if the services are
refused (a service deactivated while the form was open) the whole save is
rolled back rather than half-applied.
"""

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.core.db import DbSession
from app.core.errors import AppError
from app.core.pagination import PageParams
from app.schemas.provider import ProviderCreate
from app.services import provider_catalog, service_catalog
from app.services.business_settings import get_business_settings
from app.web.deps import WebAdmin
from app.web.forms import field_errors
from app.web.templating import render, set_flash

router = APIRouter(include_in_schema=False)

# A business has a handful of providers; the admin list shows them all.
ALL = PageParams(limit=200, offset=0)

_MESSAGES = {
    "name": "Enter a name, up to 100 characters.",
    "bio": "Keep the bio under 1000 characters.",
}
_SERVICES_GONE = "One of the chosen services is no longer active. Check the list and save again."


def _form(request, db, view, values, errors=None, status_code=200):
    services, _ = service_catalog.list_services(db, ALL, include_inactive=False)
    context = {
        "business": get_business_settings(db),
        "provider": view.provider if view else None,
        "values": values,
        "errors": errors or {},
        "choices": services,
    }
    return render(request, "admin/provider_form.html", context, status_code=status_code)


def _values(view) -> dict:
    return {
        "name": view.provider.name,
        "bio": view.provider.bio or "",
        "service_ids": [s.id for s in view.services],
    }


def _save(db: DbSession, provider_id: int | None, name: str, bio: str, service_ids: list[int]):
    """Returns `(provider_id, errors)`; on errors nothing has been changed."""
    try:
        body = ProviderCreate(name=name, bio=bio)
    except ValidationError as error:
        return None, field_errors(error, _MESSAGES)
    try:
        # A savepoint: if the services are refused, the provider row written
        # just before them is undone too, and nothing else in the request is.
        with db.begin_nested():
            if provider_id is None:
                provider_id = provider_catalog.create_provider(db, body.model_dump()).provider.id
            else:
                provider_catalog.update_provider(db, provider_id, body.model_dump())
            provider_catalog.replace_offered_services(db, provider_id, service_ids)
    except AppError as error:
        if error.code != "UNKNOWN_SERVICE":
            raise
        return None, {"service_ids": _SERVICES_GONE}
    return provider_id, {}


@router.get("/admin/providers", response_class=HTMLResponse, name="admin_providers")
def providers_list(request: Request, db: DbSession, admin: WebAdmin) -> HTMLResponse:
    views, _ = provider_catalog.list_providers(db, ALL, include_inactive=True, service_id=None)
    context = {"business": get_business_settings(db), "providers": views}
    return render(request, "admin/providers.html", context)


@router.get("/admin/providers/new", response_class=HTMLResponse, name="admin_provider_new")
def new_form(request: Request, db: DbSession, admin: WebAdmin) -> HTMLResponse:
    return _form(request, db, None, {"service_ids": []})


@router.post("/admin/providers", name="admin_provider_create")
def create(
    request: Request,
    db: DbSession,
    admin: WebAdmin,
    name: Annotated[str, Form()] = "",
    bio: Annotated[str, Form()] = "",
    service_ids: Annotated[list[int], Form()] = [],  # noqa: B006 - FastAPI copies the default
) -> Response:
    """Raises: nothing; a bad form is shown again (422)."""
    provider_id, errors = _save(db, None, name, bio, service_ids)
    if errors:
        values = {"name": name, "bio": bio, "service_ids": service_ids}
        return _form(request, db, None, values, errors, 422)
    response = RedirectResponse("/admin/providers", status_code=303)
    set_flash(response, "provider_saved")
    return response


@router.get(
    "/admin/providers/{provider_id}/edit", response_class=HTMLResponse, name="admin_provider_edit"
)
def edit_form(request: Request, provider_id: int, db: DbSession, admin: WebAdmin) -> HTMLResponse:
    """Raises: 404 `NOT_FOUND`."""
    view = provider_catalog.get_provider(db, provider_id, include_inactive=True)
    return _form(request, db, view, _values(view))


@router.post("/admin/providers/{provider_id}", name="admin_provider_update")
def update(
    request: Request,
    provider_id: int,
    db: DbSession,
    admin: WebAdmin,
    name: Annotated[str, Form()] = "",
    bio: Annotated[str, Form()] = "",
    service_ids: Annotated[list[int], Form()] = [],  # noqa: B006 - FastAPI copies the default
) -> Response:
    """Raises: 404 `NOT_FOUND`; a bad form is shown again (422)."""
    view = provider_catalog.get_provider(db, provider_id, include_inactive=True)
    _, errors = _save(db, provider_id, name, bio, service_ids)
    if errors:
        values = {"name": name, "bio": bio, "service_ids": service_ids}
        return _form(request, db, view, values, errors, 422)
    response = RedirectResponse("/admin/providers", status_code=303)
    set_flash(response, "provider_saved")
    return response


@router.post("/admin/providers/{provider_id}/activate", name="admin_provider_activate")
def activate(provider_id: int, db: DbSession, admin: WebAdmin) -> Response:
    """Raises: 404 `NOT_FOUND`."""
    provider_catalog.set_provider_active(db, provider_id, active=True)
    response = RedirectResponse("/admin/providers", status_code=303)
    set_flash(response, "provider_activated")
    return response


@router.post("/admin/providers/{provider_id}/deactivate", name="admin_provider_deactivate")
def deactivate(provider_id: int, db: DbSession, admin: WebAdmin) -> Response:
    """Raises: 404 `NOT_FOUND`."""
    provider_catalog.set_provider_active(db, provider_id, active=False)
    response = RedirectResponse("/admin/providers", status_code=303)
    set_flash(response, "provider_deactivated")
    return response
