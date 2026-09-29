"""/settings: the business's timezone, currency and booking policy."""

from fastapi import APIRouter

from app.api.deps import AdminUser
from app.core.db import DbSession
from app.schemas.business_settings import SettingsResponse, SettingsUpdate
from app.schemas.errors import ErrorResponse
from app.services import business_settings as settings_service

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsResponse, summary="Business settings (public)")
def read_settings(db: DbSession) -> SettingsResponse:
    """Public: clients need the timezone and booking limits to show slots and dates."""
    return SettingsResponse.model_validate(settings_service.get_business_settings(db))


@router.patch(
    "",
    response_model=SettingsResponse,
    summary="Change business settings (admin)",
    responses={
        401: {"model": ErrorResponse, "description": "Not logged in."},
        403: {"model": ErrorResponse, "description": "`FORBIDDEN`: not an administrator."},
        409: {
            "model": ErrorResponse,
            "description": (
                "`GRANULARITY_CONFLICT`: active services have durations that are not a "
                "multiple of the new granularity; `details.services` lists them."
            ),
        },
        422: {
            "model": ErrorResponse,
            "description": "`VALIDATION_ERROR` (out-of-range value, empty body) or "
            "`INVALID_TIMEZONE`.",
        },
    },
)
def update_settings(body: SettingsUpdate, db: DbSession, admin: AdminUser) -> SettingsResponse:
    """Send only the fields to change. Existing bookings are never touched: they are
    stored as UTC instants and keep their price and duration."""
    changes = body.model_dump(exclude_unset=True)
    return SettingsResponse.model_validate(settings_service.update_business_settings(db, changes))
