"""GET /api/v1/health: liveness plus a database round-trip."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.errors import ErrorResponse
from app.schemas.health import HealthResponse
from app.services import health as health_service

router = APIRouter(tags=["health"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health",
    responses={503: {"model": ErrorResponse, "description": "Database unreachable"}},
)
def health(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    """Returns 200 when the app is up and the database answers `SELECT 1`."""
    health_service.check_database(db)
    return HealthResponse(status="ok", database="ok")
