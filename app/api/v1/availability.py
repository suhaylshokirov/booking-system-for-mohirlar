"""/providers/{id}/availability: the weekly hours each provider works."""

from fastapi import APIRouter, Response, status

from app.api.deps import AdminUser, OptionalUser, is_admin
from app.core.db import DbSession
from app.schemas.availability import RuleCreate, RuleResponse, RuleUpdate
from app.schemas.errors import ErrorResponse
from app.services import availability

router = APIRouter(prefix="/providers/{provider_id}/availability", tags=["availability"])

_ADMIN_ERRORS = {
    401: {"model": ErrorResponse, "description": "Not logged in."},
    403: {"model": ErrorResponse, "description": "`FORBIDDEN`: not an administrator."},
}
_NOT_FOUND = {
    404: {"model": ErrorResponse, "description": "`NOT_FOUND`: no such provider or rule."}
}
_RULE_ERRORS = {
    409: {
        "model": ErrorResponse,
        "description": "`AVAILABILITY_OVERLAP`: the window overlaps another rule of the provider "
        "on that weekday (`details.conflicting_rule`).",
    },
    422: {
        "model": ErrorResponse,
        "description": "`VALIDATION_ERROR`; `INVALID_TIME_RANGE`: the end is not after the "
        "start; `MISALIGNED_TIME`: a time is not a multiple of the slot granularity.",
    },
}


@router.get(
    "/rules",
    response_model=list[RuleResponse],
    summary="A provider's weekly working hours (public)",
    responses=_NOT_FOUND,
)
def list_rules(provider_id: int, db: DbSession, user: OptionalUser) -> list[RuleResponse]:
    """Local times in the business timezone (see `GET /settings`), Monday first.
    An inactive provider is `404` for everyone but admins."""
    rules = availability.list_rules(db, provider_id, include_inactive=is_admin(user))
    return [RuleResponse.model_validate(rule) for rule in rules]


@router.post(
    "/rules",
    response_model=RuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a weekly working window (admin)",
    responses={**_ADMIN_ERRORS, **_NOT_FOUND, **_RULE_ERRORS},
)
def create_rule(
    provider_id: int, body: RuleCreate, db: DbSession, admin: AdminUser
) -> RuleResponse:
    """Windows that touch (12:00 ends, 12:00 starts) are allowed; windows that overlap are not."""
    return RuleResponse.model_validate(availability.create_rule(db, provider_id, body.model_dump()))


@router.patch(
    "/rules/{rule_id}",
    response_model=RuleResponse,
    summary="Change a weekly working window (admin)",
    responses={**_ADMIN_ERRORS, **_NOT_FOUND, **_RULE_ERRORS},
)
def update_rule(
    provider_id: int, rule_id: int, body: RuleUpdate, db: DbSession, admin: AdminUser
) -> RuleResponse:
    rule = availability.update_rule(db, provider_id, rule_id, body.changes())
    return RuleResponse.model_validate(rule)


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a weekly working window (admin)",
    responses={**_ADMIN_ERRORS, **_NOT_FOUND},
)
def delete_rule(provider_id: int, rule_id: int, db: DbSession, admin: AdminUser) -> Response:
    """Existing bookings are never removed; the admin sees which ones no longer fit
    once P4.4 lands."""
    availability.delete_rule(db, provider_id, rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
