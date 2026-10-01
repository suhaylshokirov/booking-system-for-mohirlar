"""/services: the catalog customers pick from, managed by the barbers."""

from fastapi import APIRouter, status

from app.api.deps import BarberUser, IncludeInactive, OptionalUser, is_barber
from app.core.db import DbSession
from app.core.pagination import PageParamsDep
from app.schemas.errors import ErrorResponse
from app.schemas.pagination import Page
from app.schemas.service import ServiceCreate, ServiceResponse, ServiceUpdate
from app.services import service_catalog

router = APIRouter(prefix="/services", tags=["services"])

_BARBER_ERRORS = {
    401: {"model": ErrorResponse, "description": "Not logged in."},
    403: {"model": ErrorResponse, "description": "`FORBIDDEN`: not a barber."},
}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "`NOT_FOUND`: no such service."}}
_NOT_ALIGNED = {
    422: {
        "model": ErrorResponse,
        "description": "`VALIDATION_ERROR`, or `DURATION_NOT_ALIGNED`: the duration is not a "
        "multiple of the slot granularity in the business settings.",
    }
}


@router.get(
    "",
    response_model=Page[ServiceResponse],
    summary="List services (public)",
    responses={
        401: {"model": ErrorResponse, "description": "`include_inactive` without logging in."},
        403: {"model": ErrorResponse, "description": "`include_inactive` by a non-barber."},
    },
)
def list_services(
    db: DbSession,
    params: PageParamsDep,
    include_inactive: IncludeInactive,
) -> Page[ServiceResponse]:
    """Active services, alphabetical. Barbers may pass `include_inactive=true`."""
    items, total = service_catalog.list_services(db, params, include_inactive=include_inactive)
    return Page[ServiceResponse](
        items=[ServiceResponse.model_validate(item) for item in items],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get(
    "/{service_id}",
    response_model=ServiceResponse,
    summary="One service (public)",
    responses=_NOT_FOUND,
)
def read_service(service_id: int, db: DbSession, user: OptionalUser) -> ServiceResponse:
    """An inactive service is `404` for everyone but barbers."""
    service = service_catalog.get_service(db, service_id, include_inactive=is_barber(user))
    return ServiceResponse.model_validate(service)


@router.post(
    "",
    response_model=ServiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a service (barber)",
    responses={**_BARBER_ERRORS, **_NOT_ALIGNED},
)
def create_service(body: ServiceCreate, db: DbSession, barber: BarberUser) -> ServiceResponse:
    service = service_catalog.create_service(db, body.model_dump())
    return ServiceResponse.model_validate(service)


@router.patch(
    "/{service_id}",
    response_model=ServiceResponse,
    summary="Change a service (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND, **_NOT_ALIGNED},
)
def update_service(
    service_id: int, body: ServiceUpdate, db: DbSession, barber: BarberUser
) -> ServiceResponse:
    """Send only the fields to change. Existing bookings keep the price and
    duration they were made with."""
    service = service_catalog.update_service(db, service_id, body.model_dump(exclude_unset=True))
    return ServiceResponse.model_validate(service)


@router.post(
    "/{service_id}/deactivate",
    response_model=ServiceResponse,
    summary="Hide a service from customers (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND},
)
def deactivate_service(service_id: int, db: DbSession, barber: BarberUser) -> ServiceResponse:
    """Services are never deleted. Existing bookings are kept as they are."""
    service = service_catalog.set_service_active(db, service_id, active=False)
    return ServiceResponse.model_validate(service)


@router.post(
    "/{service_id}/activate",
    response_model=ServiceResponse,
    summary="Show a service to customers again (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND, **_NOT_ALIGNED},
)
def activate_service(service_id: int, db: DbSession, barber: BarberUser) -> ServiceResponse:
    service = service_catalog.set_service_active(db, service_id, active=True)
    return ServiceResponse.model_validate(service)
