"""/providers/{id}/availability: the weekly hours each provider works."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import OptionalUser, OwnProvider, is_barber
from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.schemas.availability import (
    ConflictDetails,
    ConflictResponse,
    DeleteResponse,
    ExceptionCreate,
    ExceptionResponse,
    ExceptionUpdate,
    ExceptionWriteResponse,
    RuleCreate,
    RuleResponse,
    RuleUpdate,
    RuleWriteResponse,
)
from app.schemas.errors import ErrorResponse
from app.services import availability

router = APIRouter(prefix="/providers/{provider_id}/availability", tags=["availability"])

ClockDep = Annotated[Clock, Depends(get_clock)]


def _conflicts(db: Session, provider_id: int, clock: Clock) -> ConflictDetails:
    """The warning attached to every availability change: what no longer fits."""
    found = availability.find_conflicts(db, provider_id, clock.now())
    return ConflictDetails(conflicts=[ConflictResponse.from_conflict(c) for c in found])


def _rule_write(db: Session, rule, clock: Clock) -> RuleWriteResponse:
    details = _conflicts(db, rule.provider_id, clock)
    return RuleWriteResponse(**RuleResponse.model_validate(rule).model_dump(), details=details)


def _exception_write(db: Session, row, clock: Clock) -> ExceptionWriteResponse:
    details = _conflicts(db, row.provider_id, clock)
    return ExceptionWriteResponse(
        **ExceptionResponse.model_validate(row).model_dump(exclude={"is_day_off"}),
        details=details,
    )


_BARBER_ERRORS = {
    401: {"model": ErrorResponse, "description": "Not logged in."},
    403: {
        "model": ErrorResponse,
        "description": "`FORBIDDEN`: not a barber, or not your own hours.",
    },
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
    An inactive provider is `404` for everyone but barbers."""
    rules = availability.list_rules(db, provider_id, include_inactive=is_barber(user))
    return [RuleResponse.model_validate(rule) for rule in rules]


@router.post(
    "/rules",
    response_model=RuleWriteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a weekly working window (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND, **_RULE_ERRORS},
)
def create_rule(
    provider_id: int, body: RuleCreate, db: DbSession, barber: OwnProvider, clock: ClockDep
) -> RuleWriteResponse:
    """Windows that touch (12:00 ends, 12:00 starts) are allowed; windows that overlap are not."""
    rule = availability.create_rule(db, provider_id, body.model_dump())
    return _rule_write(db, rule, clock)


@router.patch(
    "/rules/{rule_id}",
    response_model=RuleWriteResponse,
    summary="Change a weekly working window (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND, **_RULE_ERRORS},
)
def update_rule(
    provider_id: int,
    rule_id: int,
    body: RuleUpdate,
    db: DbSession,
    barber: OwnProvider,
    clock: ClockDep,
) -> RuleWriteResponse:
    """Change a weekly window of your own. The result is checked as a whole (grid,
    end after start, no overlap on that weekday). Bookings that no longer fit are
    listed in `details.conflicts`; none is touched."""
    rule = availability.update_rule(db, provider_id, rule_id, body.changes())
    return _rule_write(db, rule, clock)


@router.delete(
    "/rules/{rule_id}",
    response_model=DeleteResponse,
    summary="Remove a weekly working window (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND},
)
def delete_rule(
    provider_id: int, rule_id: int, db: DbSession, barber: OwnProvider, clock: ClockDep
) -> DeleteResponse:
    """Existing bookings are never removed; `details.conflicts` lists the ones that no
    longer fit."""
    availability.delete_rule(db, provider_id, rule_id)
    return DeleteResponse(id=rule_id, details=_conflicts(db, provider_id, clock))


_EXCEPTION_ERRORS = {
    409: {
        "model": ErrorResponse,
        "description": "`AVAILABILITY_EXCEPTION_EXISTS`: the provider already has an exception "
        "for that date.",
    },
    422: {
        "model": ErrorResponse,
        "description": "`VALIDATION_ERROR`; `DATE_IN_PAST`: before today in the business "
        "timezone; `INVALID_TIME_RANGE`; `MISALIGNED_TIME`.",
    },
}


@router.get(
    "/exceptions",
    response_model=list[ExceptionResponse],
    summary="A barber's days off and custom-hours dates",
    responses={**_BARBER_ERRORS, **_NOT_FOUND},
)
def list_exceptions(
    provider_id: int, db: DbSession, barber: OwnProvider
) -> list[ExceptionResponse]:
    """Earliest date first, past dates included. Barber-only because a reason
    ("sick leave") is not for customers; they only see the resulting slots."""
    rows = availability.list_exceptions(db, provider_id)
    return [ExceptionResponse.model_validate(row) for row in rows]


@router.post(
    "/exceptions",
    response_model=ExceptionWriteResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Close a date or give it custom hours (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND, **_EXCEPTION_ERRORS},
)
def create_exception(
    provider_id: int,
    body: ExceptionCreate,
    db: DbSession,
    barber: OwnProvider,
    clock: ClockDep,
) -> ExceptionWriteResponse:
    """The exception **replaces** the weekly rules for that date. Send no times for a
    day off, or both times for one custom window. Bookings already made for the
    date are not touched."""
    row = availability.create_exception(db, provider_id, body.model_dump(), clock)
    return _exception_write(db, row, clock)


@router.patch(
    "/exceptions/{exception_id}",
    response_model=ExceptionWriteResponse,
    summary="Change an exception (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND, **_EXCEPTION_ERRORS},
)
def update_exception(
    provider_id: int,
    exception_id: int,
    body: ExceptionUpdate,
    db: DbSession,
    barber: OwnProvider,
    clock: ClockDep,
) -> ExceptionWriteResponse:
    """`null` times make it a day off. An exception in the past cannot be edited."""
    row = availability.update_exception(db, provider_id, exception_id, body.changes(), clock)
    return _exception_write(db, row, clock)


@router.delete(
    "/exceptions/{exception_id}",
    response_model=DeleteResponse,
    summary="Remove an exception (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND},
)
def delete_exception(
    provider_id: int, exception_id: int, db: DbSession, barber: OwnProvider, clock: ClockDep
) -> DeleteResponse:
    """The weekly rules apply to that date again; `details.conflicts` lists bookings
    that still do not fit them."""
    availability.delete_exception(db, provider_id, exception_id)
    return DeleteResponse(id=exception_id, details=_conflicts(db, provider_id, clock))


@router.get(
    "/conflicts",
    response_model=list[ConflictResponse],
    summary="Future bookings that no longer fit the provider's hours (barber)",
    responses={**_BARBER_ERRORS, **_NOT_FOUND},
)
def list_conflicts(
    provider_id: int, db: DbSession, barber: OwnProvider, clock: ClockDep
) -> list[ConflictResponse]:
    """Pending and confirmed bookings that have not started, earliest first, that
    are not fully inside the provider's working hours (weekly rules, or the
    exception for their date). Nothing is changed: the barber decides what to do."""
    return _conflicts(db, provider_id, clock).conflicts
