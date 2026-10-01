"""Services (what can be booked): create, list, edit, deactivate.

Rules:
* A duration must be a multiple of the business's slot granularity, otherwise
  slots could not line up with it.
* Services are deactivated, never deleted (bookings reference them and copy the
  price and duration, so editing or deactivating one never changes a booking).
* Inactive services are invisible to everyone except barbers: a missing
  service and an inactive one look the same to a customer (404).

Every write that depends on the granularity reads the settings row with a lock,
so a concurrent granularity change (which checks existing services) cannot slip
a misaligned service in between.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.pagination import PageParams, paginate
from app.models.service import Service
from app.services.business_settings import get_business_settings


def _ensure_aligned(duration_minutes: int, granularity: int) -> None:
    if duration_minutes % granularity != 0:
        raise AppError(
            "DURATION_NOT_ALIGNED",
            f"A service must last a multiple of {granularity} minutes.",
            status_code=422,
            details={"duration_minutes": duration_minutes, "slot_granularity_minutes": granularity},
        )


def _not_found() -> AppError:
    return AppError("NOT_FOUND", "Service not found.", status_code=404)


def list_services(
    db: Session, params: PageParams, *, include_inactive: bool
) -> tuple[list[Service], int]:
    """One page of services, alphabetical; active only unless `include_inactive`."""
    query = select(Service).order_by(Service.name, Service.id)
    if not include_inactive:
        query = query.where(Service.is_active)
    return paginate(db, query, params)


def get_service(db: Session, service_id: int, *, include_inactive: bool) -> Service:
    """Raises: 404 `NOT_FOUND` if missing, or inactive and `include_inactive` is False."""
    service = db.get(Service, service_id)
    if service is None or (not service.is_active and not include_inactive):
        raise _not_found()
    return service


def create_service(db: Session, data: dict[str, Any]) -> Service:
    """Raises: 422 `DURATION_NOT_ALIGNED`."""
    settings = get_business_settings(db, for_update=True)
    _ensure_aligned(data["duration_minutes"], settings.slot_granularity_minutes)
    service = Service(**data)
    db.add(service)
    db.flush()
    return service


def update_service(db: Session, service_id: int, changes: dict[str, Any]) -> Service:
    """Apply the given fields to any service, active or not.

    Raises: 404 `NOT_FOUND`; 422 `DURATION_NOT_ALIGNED` when the duration changes.
    """
    settings = get_business_settings(db, for_update=True)
    service = get_service(db, service_id, include_inactive=True)
    if "duration_minutes" in changes:
        _ensure_aligned(changes["duration_minutes"], settings.slot_granularity_minutes)
    for field, value in changes.items():
        setattr(service, field, value)
    db.flush()
    return service


def set_service_active(db: Session, service_id: int, *, active: bool) -> Service:
    """Deactivate or reactivate. Repeating the current state is a harmless no-op.

    Deactivating keeps every booking. Reactivating re-checks the duration
    because the granularity may have changed while the service was inactive.

    Raises: 404 `NOT_FOUND`; 422 `DURATION_NOT_ALIGNED` on reactivation.
    """
    settings = get_business_settings(db, for_update=True)
    service = get_service(db, service_id, include_inactive=True)
    if active and not service.is_active:
        _ensure_aligned(service.duration_minutes, settings.slot_granularity_minutes)
    service.is_active = active
    db.flush()
    return service
