"""Business settings: the one row of timezone, currency and booking policy.

Rules: the timezone must be a real IANA zone, and the slot granularity may only
change to a value every active service's duration is a multiple of, so no
service is left unbookable. Value ranges (lead time, horizon, cutoff) are
checked by the request schema and, as a backstop, by CHECK constraints.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.timezones import is_valid_timezone
from app.models.business_settings import BusinessSettings
from app.models.service import Service

DEFAULT_NAME = "Navbat"


def get_business_settings(db: Session, *, for_update: bool = False) -> BusinessSettings:
    """The settings row, created with the column defaults if it does not exist.

    A freshly migrated database has no row (only the seed script adds one), so
    creating it here keeps a new deployment working before anyone has visited
    the admin. `ON CONFLICT DO NOTHING` makes two simultaneous first requests
    safe: one inserts, the other's insert is a no-op, both then read the row.

    `for_update` locks the row until the transaction ends, so two changes to the
    settings (or a settings change and a service being created, which must read
    it with a lock too) cannot both act on stale values.
    """
    db.execute(
        insert(BusinessSettings)
        .values(id=1, name=DEFAULT_NAME)
        .on_conflict_do_nothing(index_elements=["id"])
    )
    query = select(BusinessSettings).where(BusinessSettings.id == 1)
    if for_update:
        query = query.with_for_update()
    return db.scalars(query).one()


def update_business_settings(db: Session, changes: dict[str, Any]) -> BusinessSettings:
    """Apply the given fields (already shape-validated) and return the row.

    Raises:
        AppError: 422 `INVALID_TIMEZONE` for a name that is not an IANA zone;
            409 `GRANULARITY_CONFLICT` when an active service's duration is not
            a multiple of the new granularity (`details.services` lists them).
    """
    settings = get_business_settings(db, for_update=True)

    timezone = changes.get("timezone")
    if timezone is not None and not is_valid_timezone(timezone):
        raise AppError(
            "INVALID_TIMEZONE",
            f"'{timezone}' is not an IANA timezone name such as 'Asia/Tashkent'.",
            status_code=422,
            details={"timezone": timezone},
        )

    granularity = changes.get("slot_granularity_minutes")
    if granularity is not None and granularity != settings.slot_granularity_minutes:
        _ensure_services_fit(db, granularity)

    for field, value in changes.items():
        setattr(settings, field, value)
    db.flush()
    return settings


def _ensure_services_fit(db: Session, granularity: int) -> None:
    """Refuse a granularity that active services' durations don't divide by.

    Inactive services are ignored: they can't be booked. (Reactivating one must
    re-check alignment, which is P3.2's job.)
    """
    misaligned = db.execute(
        select(Service.id, Service.name, Service.duration_minutes)
        .where(Service.is_active, Service.duration_minutes % granularity != 0)
        .order_by(Service.id)
    ).all()
    if misaligned:
        raise AppError(
            "GRANULARITY_CONFLICT",
            f"Active services have durations that are not a multiple of {granularity} minutes. "
            "Change or deactivate them first.",
            status_code=409,
            details={
                "slot_granularity_minutes": granularity,
                "services": [
                    {"id": row.id, "name": row.name, "duration_minutes": row.duration_minutes}
                    for row in misaligned
                ],
            },
        )
