"""/providers: the barbers customers book with. Each barber manages their own profile.

There is no endpoint to create a provider: a provider exists because a barber account
was created for them (`scripts/create_barber.py`, ADR 0010).

A barber's photo has its own three routes (`/providers/{id}/photo`): it is a file,
not a JSON field, so it is uploaded as `multipart/form-data` and served as the image
itself. The rules are in `services/provider_photo.py`.
"""

from typing import Annotated

from fastapi import APIRouter, File, Query, Response, UploadFile

from app.api.deps import IncludeInactive, OptionalUser, OwnProvider, is_barber
from app.core.db import DbSession
from app.core.pagination import PageParamsDep
from app.schemas.errors import ErrorResponse
from app.schemas.pagination import Page, page_response
from app.schemas.provider import (
    OfferedServices,
    ProviderResponse,
    ProviderUpdate,
)
from app.services import provider_catalog, provider_photo

router = APIRouter(prefix="/providers", tags=["providers"])

_BARBER_ERRORS = {
    401: {"model": ErrorResponse, "description": "Not logged in."},
    403: {
        "model": ErrorResponse,
        "description": "`FORBIDDEN`: not a barber, or not your profile.",
    },
}
_NOT_FOUND = {404: {"model": ErrorResponse, "description": "`NOT_FOUND`: no such provider."}}


@router.get(
    "",
    response_model=Page[ProviderResponse],
    summary="List providers (public)",
    responses={
        **page_response(ProviderResponse),
        401: {"model": ErrorResponse, "description": "`include_inactive` without logging in."},
        403: {"model": ErrorResponse, "description": "`include_inactive` by a non-barber."},
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
    """An inactive provider is `404` for everyone but barbers."""
    view = provider_catalog.get_provider(db, provider_id, include_inactive=is_barber(user))
    return ProviderResponse.from_view(view)


@router.patch(
    "/{provider_id}",
    response_model=ProviderResponse,
    summary="Change a provider (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND},
)
def update_provider(
    provider_id: int, body: ProviderUpdate, db: DbSession, barber: OwnProvider
) -> ProviderResponse:
    """Change your own name or bio. Send only the fields to change. Another barber's
    provider id is `403 FORBIDDEN`."""
    view = provider_catalog.update_provider(db, provider_id, body.model_dump(exclude_unset=True))
    return ProviderResponse.from_view(view)


@router.post(
    "/{provider_id}/deactivate",
    response_model=ProviderResponse,
    summary="Hide a provider from customers (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND},
)
def deactivate_provider(provider_id: int, db: DbSession, barber: OwnProvider) -> ProviderResponse:
    """Providers are never deleted. Existing bookings are kept as they are."""
    view = provider_catalog.set_provider_active(db, provider_id, active=False)
    return ProviderResponse.from_view(view)


@router.post(
    "/{provider_id}/activate",
    response_model=ProviderResponse,
    summary="Show a provider to customers again (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND},
)
def activate_provider(provider_id: int, db: DbSession, barber: OwnProvider) -> ProviderResponse:
    """Show yourself to customers again after hiding. Repeating it is harmless."""
    view = provider_catalog.set_provider_active(db, provider_id, active=True)
    return ProviderResponse.from_view(view)


@router.put(
    "/{provider_id}/services",
    response_model=ProviderResponse,
    summary="Set which services a provider offers (barber)",
    responses={
        **_BARBER_ERRORS,
        **_NOT_FOUND,
        422: {
            "model": ErrorResponse,
            "description": "`VALIDATION_ERROR`, or `UNKNOWN_SERVICE`: an id is not an existing, "
            "active service (`details.service_ids` lists them; nothing is changed).",
        },
    },
)
def replace_offered_services(
    provider_id: int, body: OfferedServices, db: DbSession, barber: OwnProvider
) -> ProviderResponse:
    """Replaces the whole set. Send `[]` for "offers nothing". Bookings already made
    for a service that is removed here are kept."""
    view = provider_catalog.replace_offered_services(db, provider_id, body.service_ids)
    return ProviderResponse.from_view(view)


# --- photo ---------------------------------------------------------------------------

# The photo changes rarely and its URL carries a version (`photo_url`), so a day
# of browser caching is safe. `nosniff` makes browsers trust the declared type
# instead of guessing from the bytes.
_PHOTO_HEADERS = {"Cache-Control": "max-age=86400", "X-Content-Type-Options": "nosniff"}


@router.get(
    "/{provider_id}/photo",
    response_class=Response,
    summary="A provider's photo (public)",
    responses={
        200: {
            "description": "The image itself, as JPEG, PNG or WebP.",
            "content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}},
        },
        404: {
            "model": ErrorResponse,
            "description": "`NOT_FOUND`: no such provider, or they have no photo. An inactive "
            "provider's photo is `404` for everyone but barbers.",
        },
    },
)
def read_photo(provider_id: int, db: DbSession, user: OptionalUser) -> Response:
    """The bytes as uploaded, with the media type the upload was recognised as. Use the
    provider's `photo_url`, which changes when the photo does."""
    data, media_type = provider_photo.get_photo(db, provider_id, include_inactive=is_barber(user))
    return Response(content=data, media_type=media_type, headers=_PHOTO_HEADERS)


@router.put(
    "/{provider_id}/photo",
    response_model=ProviderResponse,
    summary="Upload or replace your photo (barber)",
    responses={
        **_BARBER_ERRORS,
        **_NOT_FOUND,
        413: {"model": ErrorResponse, "description": "`PHOTO_TOO_LARGE`: over 2 MB."},
        415: {
            "model": ErrorResponse,
            "description": "`UNSUPPORTED_PHOTO`: not a JPEG, PNG or WebP image.",
        },
    },
)
def upload_photo(
    provider_id: int,
    photo: Annotated[
        UploadFile,
        File(description="JPEG, PNG or WebP, at most 2 MB. Judged by its content, not its name."),
    ],
    db: DbSession,
    barber: OwnProvider,
) -> ProviderResponse:
    """Send the file as `multipart/form-data` in a field named `photo`. It replaces any
    earlier photo; on an error nothing is changed."""
    view = provider_photo.set_photo(db, provider_id, provider_photo.read_upload(photo.file))
    return ProviderResponse.from_view(view)


@router.delete(
    "/{provider_id}/photo",
    response_model=ProviderResponse,
    summary="Remove your photo (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND},
)
def delete_photo(provider_id: int, db: DbSession, barber: OwnProvider) -> ProviderResponse:
    """Customers see your initial instead. Removing a photo that is not there is harmless."""
    view = provider_photo.remove_photo(db, provider_id)
    return ProviderResponse.from_view(view)
