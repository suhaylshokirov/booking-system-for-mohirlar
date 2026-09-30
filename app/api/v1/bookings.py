"""/bookings: a customer books and looks at their own bookings."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser
from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.core.pagination import PageParamsDep
from app.models.booking import BookingStatus
from app.schemas.booking import BookingCreate, BookingResponse
from app.schemas.errors import ErrorResponse
from app.schemas.pagination import Page
from app.services import booking as booking_service

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
