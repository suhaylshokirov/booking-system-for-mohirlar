"""/slots: the free start times the booking UI shows. Public, read-only."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.schemas.errors import ErrorResponse
from app.schemas.slots import SlotsResponse
from app.services import slot_query

router = APIRouter(prefix="/slots", tags=["slots"])

ClockDep = Annotated[Clock, Depends(get_clock)]


@router.get(
    "",
    response_model=SlotsResponse,
    summary="Free time slots for a service on a date (public)",
    responses={
        404: {
            "model": ErrorResponse,
            "description": "`NOT_FOUND`: unknown or inactive service or provider.",
        },
        422: {
            "model": ErrorResponse,
            "description": "`VALIDATION_ERROR`, `DATE_OUT_OF_RANGE` (before today or beyond the "
            "booking horizon; `details` has `earliest` and `latest`), or "
            "`PROVIDER_DOES_NOT_OFFER_SERVICE`.",
        },
    },
)
def read_slots(
    db: DbSession,
    clock: ClockDep,
    service_id: Annotated[int, Query(description="The service to book.")],
    day: Annotated[date, Query(alias="date", description="Local date, `YYYY-MM-DD`.")],
    provider_id: Annotated[
        int | None, Query(description="Only this provider; omit for every provider offering it.")
    ] = None,
) -> SlotsResponse:
    """Start times are UTC instants. The list is advisory: a slot can still be
    taken by someone else before you book it (`409 SLOT_TAKEN`)."""
    result = slot_query.get_slots(db, service_id, day, provider_id, clock.now())
    return SlotsResponse.from_result(result)
