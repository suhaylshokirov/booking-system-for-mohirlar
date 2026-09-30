"""/bookings: a customer books, looks at and cancels their own; an admin runs them all."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AdminUser, CurrentUser
from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.core.pagination import PageParamsDep
from app.models.booking import BookingStatus
from app.schemas.booking import (
    AdminBookingResponse,
    BookingCreate,
    BookingEventResponse,
    BookingResponse,
    CancelRequest,
    EventActor,
)
from app.schemas.errors import ErrorResponse
from app.schemas.pagination import Page
from app.services import booking as booking_service
from app.services.booking_state import is_stale_pending

router = APIRouter(prefix="/bookings", tags=["bookings"])

ClockDep = Annotated[Clock, Depends(get_clock)]

_UNAUTHENTICATED = {401: {"model": ErrorResponse, "description": "Not logged in."}}


@router.post(
    "",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Book an appointment",
    responses={
        **_UNAUTHENTICATED,
        404: {"model": ErrorResponse, "description": "`NOT_FOUND`: no such service or provider."},
        409: {
            "model": ErrorResponse,
            "description": "`SLOT_TAKEN` (the provider is busy then) or `CUSTOMER_OVERLAP` "
            "(you already have a booking at that time).",
        },
        422: {
            "model": ErrorResponse,
            "description": "`VALIDATION_ERROR` (including a `start_at` without a UTC offset), "
            "or a booking rule: `SERVICE_INACTIVE`, `PROVIDER_INACTIVE`, "
            "`PROVIDER_DOES_NOT_OFFER_SERVICE`, `START_IN_PAST`, `INSIDE_LEAD_TIME`, "
            "`BEYOND_HORIZON`, `OUTSIDE_AVAILABILITY`, `NOT_ALIGNED`.",
        },
    },
)
def create_booking(
    body: BookingCreate, db: DbSession, user: CurrentUser, clock: ClockDep
) -> BookingResponse:
    """Creates a `pending` booking. Price and duration are copied from the
    service now, so a later edit to the service does not change this booking."""
    booking = booking_service.create_booking(
        db, user, body.service_id, body.provider_id, body.start_at, body.notes, clock.now()
    )
    return BookingResponse.model_validate(booking)


@router.get(
    "",
    response_model=Page[BookingResponse],
    summary="List my bookings",
    responses=_UNAUTHENTICATED,
)
def list_bookings(
    db: DbSession,
    user: CurrentUser,
    clock: ClockDep,
    params: PageParamsDep,
    scope: Annotated[
        booking_service.Scope | None,
        Query(description="`upcoming`: not over yet, soonest first. `past`: over, latest first."),
    ] = None,
    booking_status: Annotated[
        BookingStatus | None, Query(alias="status", description="Only this status.")
    ] = None,
) -> Page[BookingResponse]:
    """Your own bookings only, including an admin's own."""
    items, total = booking_service.list_my_bookings(
        db, user, params, clock.now(), scope, booking_status
    )
    return Page[BookingResponse](
        items=[BookingResponse.model_validate(item) for item in items],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get(
    "/all",
    response_model=Page[AdminBookingResponse],
    summary="List every booking (admin)",
    responses={
        **_UNAUTHENTICATED,
        403: {"model": ErrorResponse, "description": "`FORBIDDEN`: not an administrator."},
    },
)
def list_all_bookings(
    db: DbSession,
    admin: AdminUser,
    clock: ClockDep,
    params: PageParamsDep,
    booking_status: Annotated[
        BookingStatus | None, Query(alias="status", description="Only this status.")
    ] = None,
    provider_id: Annotated[int | None, Query(description="Only this provider.")] = None,
    customer_id: Annotated[int | None, Query(description="Only this customer.")] = None,
    date_from: Annotated[
        dt.date | None, Query(description="First day (business-local, inclusive) it starts on.")
    ] = None,
    date_to: Annotated[
        dt.date | None, Query(description="Last day (business-local, inclusive) it starts on.")
    ] = None,
) -> Page[AdminBookingResponse]:
    """All customers' bookings, soonest start first. `stale_pending` marks pending
    bookings whose time has passed."""
    now = clock.now()
    items, total = booking_service.list_all_bookings(
        db, params, booking_status, provider_id, customer_id, date_from, date_to
    )
    return Page[AdminBookingResponse](
        items=[
            AdminBookingResponse(
                **BookingResponse.model_validate(item).model_dump(),
                stale_pending=is_stale_pending(item, now),
            )
            for item in items
        ],
        total=total,
        limit=params.limit,
        offset=params.offset,
    )


@router.get(
    "/{booking_id}",
    response_model=BookingResponse,
    summary="One booking",
    responses={
        **_UNAUTHENTICATED,
        404: {
            "model": ErrorResponse,
            "description": "`BOOKING_NOT_FOUND`: no such booking, or it is someone else's "
            "(404, not 403, so ids cannot be probed). Admins can read any booking.",
        },
    },
)
def read_booking(booking_id: int, db: DbSession, user: CurrentUser) -> BookingResponse:
    return BookingResponse.model_validate(booking_service.get_booking(db, user, booking_id))


@router.get(
    "/{booking_id}/history",
    response_model=list[BookingEventResponse],
    summary="A booking's history",
    responses={
        **_UNAUTHENTICATED,
        404: {
            "model": ErrorResponse,
            "description": "`BOOKING_NOT_FOUND`: no such booking, or it is someone else's.",
        },
    },
)
def booking_history(
    booking_id: int, db: DbSession, user: CurrentUser
) -> list[BookingEventResponse]:
    """Every status change, oldest first: who, from what to what, why, and when."""
    return [
        BookingEventResponse(
            from_status=event.from_status,
            to_status=event.to_status,
            actor=EventActor(id=actor.id, role=actor.role, name=actor.full_name) if actor else None,
            reason=event.reason,
            created_at=event.created_at,
        )
        for event, actor in booking_service.list_history(db, user, booking_id)
    ]


_TRANSITION_ERRORS = {
    **_UNAUTHENTICATED,
    404: {"model": ErrorResponse, "description": "`BOOKING_NOT_FOUND` (or someone else's)."},
    409: {
        "model": ErrorResponse,
        "description": "`INVALID_TRANSITION`, `CANCELLATION_CUTOFF_PASSED` "
        "(`details.cutoff_at`), `TOO_EARLY_TO_COMPLETE`, or `BOOKING_STATE_CHANGED` "
        "(someone changed it at the same moment; reload and retry).",
    },
}


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingResponse,
    summary="Cancel a booking",
    responses={
        **_TRANSITION_ERRORS,
        422: {"model": ErrorResponse, "description": "`REASON_REQUIRED` (admin, confirmed)."},
    },
)
def cancel_booking(
    booking_id: int,
    db: DbSession,
    user: CurrentUser,
    clock: ClockDep,
    body: CancelRequest | None = None,
) -> BookingResponse:
    """Customers cancel their own; admins any. Cancelling frees the time at once."""
    reason = body.reason if body else None
    booking = booking_service.transition(
        db, user, booking_id, BookingStatus.CANCELLED, clock.now(), reason
    )
    return BookingResponse.model_validate(booking)


@router.post(
    "/{booking_id}/confirm",
    response_model=BookingResponse,
    summary="Confirm a pending booking (admin)",
    responses={
        **_TRANSITION_ERRORS,
        403: {"model": ErrorResponse, "description": "`FORBIDDEN`: not an administrator."},
    },
)
def confirm_booking(
    booking_id: int, db: DbSession, admin: AdminUser, clock: ClockDep
) -> BookingResponse:
    booking = booking_service.transition(
        db, admin, booking_id, BookingStatus.CONFIRMED, clock.now()
    )
    return BookingResponse.model_validate(booking)


@router.post(
    "/{booking_id}/complete",
    response_model=BookingResponse,
    summary="Mark a confirmed booking completed (admin)",
    responses={
        **_TRANSITION_ERRORS,
        403: {"model": ErrorResponse, "description": "`FORBIDDEN`: not an administrator."},
    },
)
def complete_booking(
    booking_id: int, db: DbSession, admin: AdminUser, clock: ClockDep
) -> BookingResponse:
    booking = booking_service.transition(
        db, admin, booking_id, BookingStatus.COMPLETED, clock.now()
    )
    return BookingResponse.model_validate(booking)
