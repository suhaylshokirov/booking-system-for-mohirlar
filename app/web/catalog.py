"""What can be booked: the home page (the shop, its services, its barbers) and one
service's page.

Customers only ever see active services and active staff; an inactive
service's page is the same 404 as one that never existed (the rule lives in
`services/service_catalog.get_service`). Thin, like every router: read through
the services, hand the result to a template.
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from app.core.db import DbSession
from app.core.pagination import MAX_LIMIT, PageParams
from app.services.business_settings import get_business_settings
from app.services.provider_catalog import list_providers
from app.services.service_catalog import get_service, list_services
from app.web.paging import MAX_PAGE, make_pager, page_params
from app.web.templating import render

router = APIRouter(include_in_schema=False)

SERVICES_PER_PAGE = 20


@router.get("/", response_class=HTMLResponse, name="home")
def home(
    request: Request,
    db: DbSession,
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
) -> HTMLResponse:
    """The shop's photos, its services (paged) and its barbers, each barber with the
    services they offer so a customer can book them directly.

    Raises: 404 for a page past the last.
    """
    business = get_business_settings(db)
    services, total = list_services(
        db, page_params(page, SERVICES_PER_PAGE), include_inactive=False
    )
    pager = make_pager(page, SERVICES_PER_PAGE, total)
    # Active barbers only, each with their active services (see provider_catalog).
    barbers, _ = list_providers(
        db, PageParams(limit=MAX_LIMIT, offset=0), include_inactive=False, service_id=None
    )
    context = {"business": business, "services": services, "pager": pager, "barbers": barbers}
    return render(request, "catalog/home.html", context)


@router.get("/services/{service_id}", response_class=HTMLResponse, name="service_detail")
def service_detail(request: Request, service_id: int, db: DbSession) -> HTMLResponse:
    """Raises: 404 `NOT_FOUND` for a missing or inactive service."""
    service = get_service(db, service_id, include_inactive=False)
    business = get_business_settings(db)
    # One page at the API's maximum: a business with more than 100 staff
    # offering one service is not what this app is for.
    staff, _ = list_providers(
        db, PageParams(limit=MAX_LIMIT, offset=0), include_inactive=False, service_id=service.id
    )
    context = {"business": business, "service": service, "staff": [v.provider for v in staff]}
    return render(request, "catalog/service.html", context)
