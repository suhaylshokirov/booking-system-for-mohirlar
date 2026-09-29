"""/providers: the staff customers book with, managed by the admin."""

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AdminUser, IncludeInactive, OptionalUser, is_admin
from app.core.db import DbSession
from app.core.pagination import PageParamsDep
from app.schemas.errors import ErrorResponse
from app.schemas.pagination import Page
from app.schemas.provider import (
    OfferedServices,
    ProviderCreate,
    ProviderResponse,
    ProviderUpdate,
)
from app.services import provider_catalog

router = APIRouter(prefix="/providers", tags=["providers"])

_ADMIN_ERRORS = {
    401: {"model": ErrorResponse, "description": "Not logged in."},
    403: {"model": ErrorResponse, "description": "`FORBIDDEN`: not an administrator."},
}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "`NOT_FOUND`: no such provider."}}


@router.get(
    "",
    response_model=Page[ProviderResponse],
    summary="List providers (public)",
    responses={
        401: {"model": ErrorResponse, "description": "`include_inactive` without logging in."},
        403: {"model": ErrorResponse, "description": "`include_inactive` by a non-admin."},
    },
)
def list_providers(
    db: DbSession,
    params: PageParamsDep,
    include_inactive: IncludeInactive,
    service_id: Annotated[
        int | None, Query(description="Only providers who offer this service.")
    ] = None,
) -> Page[ProviderResponse]:
    """Active providers with their active services, alphabetical."""
    views, total = provider_catalog.list_providers(
        db, params, include_inactive=include_inactive, service_id=service_id
    )
    return Page[ProviderResponse](
        items=[ProviderResponse.from_view(view) for view in views],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get(
    "/{provider_id}",
    response_model=ProviderResponse,
    summary="One provider with what they offer (public)",
    responses=_NOT_FOUND,
)
def read_provider(provider_id: int, db: DbSession, user: OptionalUser) -> ProviderResponse:
    """An inactive provider is `404` for everyone but admins."""
    view = provider_catalog.get_provider(db, provider_id, include_inactive=is_admin(user))
    return ProviderResponse.from_view(view)


@router.post(
    "",
    response_model=ProviderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a provider (admin)",
    responses=_ADMIN_ERRORS,
)
def create_provider(body: ProviderCreate, db: DbSession, admin: AdminUser) -> ProviderResponse:
    """A new provider offers no services yet: set them with `PUT /providers/{id}/services`."""
    return ProviderResponse.from_view(provider_catalog.create_provider(db, body.model_dump()))


@router.patch(
    "/{provider_id}",
    response_model=ProviderResponse,
    summary="Change a provider (admin)",
    responses={**_ADMIN_ERRORS, **_NOT_FOUND},
)
def update_provider(
    provider_id: int, body: ProviderUpdate, db: DbSession, admin: AdminUser
) -> ProviderResponse:
    view = provider_catalog.update_provider(db, provider_id, body.model_dump(exclude_unset=True))
    return ProviderResponse.from_view(view)


@router.post(
    "/{provider_id}/deactivate",
    response_model=ProviderResponse,
    summary="Hide a provider from customers (admin)",
    responses={**_ADMIN_ERRORS, **_NOT_FOUND},
)
def deactivate_provider(provider_id: int, db: DbSession, admin: AdminUser) -> ProviderResponse:
    """Providers are never deleted. Existing bookings are kept as they are."""
    view = provider_catalog.set_provider_active(db, provider_id, active=False)
    return ProviderResponse.from_view(view)


@router.post(
    "/{provider_id}/activate",
    response_model=ProviderResponse,
    summary="Show a provider to customers again (admin)",
    responses={**_ADMIN_ERRORS, **_NOT_FOUND},
)
def activate_provider(provider_id: int, db: DbSession, admin: AdminUser) -> ProviderResponse:
    view = provider_catalog.set_provider_active(db, provider_id, active=True)
    return ProviderResponse.from_view(view)


@router.put(
    "/{provider_id}/services",
    response_model=ProviderResponse,
    summary="Set which services a provider offers (admin)",
    responses={
        **_ADMIN_ERRORS,
        **_NOT_FOUND,
        422: {
            "model": ErrorResponse,
            "description": "`VALIDATION_ERROR`, or `UNKNOWN_SERVICE`: an id is not an existing, "
            "active service (`details.service_ids` lists them; nothing is changed).",
        },
    },
)
def replace_offered_services(
    provider_id: int, body: OfferedServices, db: DbSession, admin: AdminUser
) -> ProviderResponse:
    """Replaces the whole set. Send `[]` for "offers nothing". Bookings already made
    for a service that is removed here are kept."""
    view = provider_catalog.replace_offered_services(db, provider_id, body.service_ids)
    return ProviderResponse.from_view(view)
