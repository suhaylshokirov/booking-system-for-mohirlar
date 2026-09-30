"""Services in the admin area: list, create, edit, activate / deactivate.

    GET  /admin/services                    every service, inactive ones included
    GET  /admin/services/new                blank form
    POST /admin/services                    create
    GET  /admin/services/{id}/edit          form filled in
    POST /admin/services/{id}               save changes
    POST /admin/services/{id}/activate      (and /deactivate)

Admin only (`WebAdmin`). The same schemas (`ServiceCreate`) and service
functions (`service_catalog`) as `/api/v1/services` decide what is valid, so a
rule exists once. A problem re-renders the form with a message beside the
field and what was typed kept, status 422 like the API. The form posts
price and duration as text; `whole_number` turns them into ints (the schema
is strict, so 45.5 is refused, not rounded) and gives a message for people.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.core.db import DbSession
from app.core.errors import AppError
from app.core.pagination import PageParams
from app.schemas.service import ServiceCreate
from app.services import service_catalog
from app.services.business_settings import get_business_settings
from app.web.deps import WebAdmin
from app.web.forms import field_errors, whole_number
from app.web.templating import render, set_flash

router = APIRouter(include_in_schema=False)

# A business has a handful of services; the admin list shows them all.
ALL = PageParams(limit=200, offset=0)

_MESSAGES = {
    "name": "Enter a name, up to 100 characters.",
    "description": "Keep the description under 1000 characters.",
    "duration_minutes": "Enter the length in whole minutes, from 1 to 480.",
    "price": "Enter the price in whole UZS, for example 60000.",
}


def _form(request: Request, db: DbSession, service, values, errors=None, status_code=200):
    context = {
        "business": get_business_settings(db),
        "service": service,
        "values": values,
        "errors": errors or {},
    }
    return render(request, "admin/service_form.html", context, status_code=status_code)


def _values(service) -> dict[str, Any]:
    return {
        "name": service.name,
        "description": service.description or "",
        "duration_minutes": service.duration_minutes,
        "price": service.price,
    }


def _parse(name: str, description: str, duration_minutes: str, price: str):
    """Returns `(data, errors)`; exactly one of them is empty."""
    try:
        body = ServiceCreate(
            name=name,
            description=description,
            duration_minutes=whole_number(duration_minutes),
            price=whole_number(price),
        )
    except ValidationError as error:
        return None, field_errors(error, _MESSAGES)
    return body.model_dump(), {}


@router.get("/admin/services", response_class=HTMLResponse, name="admin_services")
def services_list(request: Request, db: DbSession, admin: WebAdmin) -> HTMLResponse:
    items, _ = service_catalog.list_services(db, ALL, include_inactive=True)
    context = {"business": get_business_settings(db), "services": items}
    return render(request, "admin/services.html", context)


@router.get("/admin/services/new", response_class=HTMLResponse, name="admin_service_new")
def new_form(request: Request, db: DbSession, admin: WebAdmin) -> HTMLResponse:
    return _form(request, db, None, {})


@router.post("/admin/services", name="admin_service_create")
def create(
    request: Request,
    db: DbSession,
    admin: WebAdmin,
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    duration_minutes: Annotated[str, Form()] = "",
    price: Annotated[str, Form()] = "",
) -> Response:
    """Raises: nothing; a bad form (including 422 `DURATION_NOT_ALIGNED`) is shown again."""
    values = {
        "name": name,
        "description": description,
        "duration_minutes": duration_minutes,
        "price": price,
    }
    data, errors = _parse(name, description, duration_minutes, price)
    if data is not None:
        try:
            service_catalog.create_service(db, data)
        except AppError as error:
            if error.code != "DURATION_NOT_ALIGNED":
                raise
            errors = {"duration_minutes": error.message}
    if errors:
        return _form(request, db, None, values, errors, 422)
    response = RedirectResponse("/admin/services", status_code=303)
    set_flash(response, "service_saved")
    return response


@router.get(
    "/admin/services/{service_id}/edit", response_class=HTMLResponse, name="admin_service_edit"
)
def edit_form(request: Request, service_id: int, db: DbSession, admin: WebAdmin) -> HTMLResponse:
    """Raises: 404 `NOT_FOUND`."""
    service = service_catalog.get_service(db, service_id, include_inactive=True)
    return _form(request, db, service, _values(service))


@router.post("/admin/services/{service_id}", name="admin_service_update")
def update(
    request: Request,
    service_id: int,
    db: DbSession,
    admin: WebAdmin,
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    duration_minutes: Annotated[str, Form()] = "",
    price: Annotated[str, Form()] = "",
) -> Response:
    """Raises: 404 `NOT_FOUND`; a bad form is shown again (422)."""
    service = service_catalog.get_service(db, service_id, include_inactive=True)
    values = {
        "name": name,
        "description": description,
        "duration_minutes": duration_minutes,
        "price": price,
    }
    data, errors = _parse(name, description, duration_minutes, price)
    if data is not None:
        try:
            service_catalog.update_service(db, service_id, data)
        except AppError as error:
            if error.code != "DURATION_NOT_ALIGNED":
                raise
            errors = {"duration_minutes": error.message}
    if errors:
        return _form(request, db, service, values, errors, 422)
    response = RedirectResponse("/admin/services", status_code=303)
    set_flash(response, "service_saved")
    return response


def _set_active(request: Request, service_id: int, db: DbSession, *, active: bool) -> Response:
    try:
        service_catalog.set_service_active(db, service_id, active=active)
    except AppError as error:
        if error.code != "DURATION_NOT_ALIGNED":
            raise
        # Reactivation re-checks the duration; send them to fix it.
        service = service_catalog.get_service(db, service_id, include_inactive=True)
        errors = {"duration_minutes": error.message}
        return _form(request, db, service, _values(service), errors, 422)
    response = RedirectResponse("/admin/services", status_code=303)
    set_flash(response, "service_activated" if active else "service_deactivated")
    return response


@router.post("/admin/services/{service_id}/activate", name="admin_service_activate")
def activate(request: Request, service_id: int, db: DbSession, admin: WebAdmin) -> Response:
    """Raises: 404 `NOT_FOUND`; an out-of-grid duration opens the edit form (422)."""
    return _set_active(request, service_id, db, active=True)


@router.post("/admin/services/{service_id}/deactivate", name="admin_service_deactivate")
def deactivate(request: Request, service_id: int, db: DbSession, admin: WebAdmin) -> Response:
    """Raises: 404 `NOT_FOUND`."""
    return _set_active(request, service_id, db, active=False)
