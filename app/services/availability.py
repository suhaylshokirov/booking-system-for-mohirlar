"""A provider's weekly availability rules: "Mondays 09:00-18:00" (local time).

Rules:
* A rule is a window on one weekday, in the business timezone. Its start and end
  must sit on the slot grid (`slot_granularity_minutes`), so every slot the
  window produces starts on a multiple of the granularity.
* A provider's rules on the same weekday must not overlap. Touching windows
  (12:00 ends, 12:00 starts) are fine, since ranges are half-open. The overlap
  is checked here to give a friendly message and enforced by the exclusion
  constraint `no_availability_rule_overlap`, which decides races.
* Rules are deleted for real: no booking references one. Bookings that no
  longer fit after an edit are reported by P4.4, never removed.
"""

from datetime import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models.availability import AvailabilityRule
from app.models.provider import Provider
from app.services.business_settings import get_business_settings

# SQLSTATE 23P01: exclusion_violation.
_EXCLUSION_VIOLATION = "23P01"
_OVERLAP_CONSTRAINT = "no_availability_rule_overlap"


def _minutes(at: time) -> int:
    return at.hour * 60 + at.minute


def _provider_not_found() -> AppError:
    return AppError("NOT_FOUND", "Provider not found.", status_code=404)


def _get_provider(
    db: Session, provider_id: int, *, include_inactive: bool, lock: bool = False
) -> Provider:
    """The provider, or 404. `lock` holds the row until the transaction ends."""
    query = select(Provider).where(Provider.id == provider_id)
    if lock:
        query = query.with_for_update()
    provider = db.scalars(query).one_or_none()
    if provider is None or (not provider.is_active and not include_inactive):
        raise _provider_not_found()
    return provider


def _get_rule(db: Session, provider_id: int, rule_id: int) -> AvailabilityRule:
    """A rule of *this* provider; another provider's rule id is just as missing."""
    rule = db.scalars(
        select(AvailabilityRule).where(
            AvailabilityRule.id == rule_id, AvailabilityRule.provider_id == provider_id
        )
    ).one_or_none()
    if rule is None:
        raise AppError("NOT_FOUND", "Availability rule not found.", status_code=404)
    return rule


def list_rules(db: Session, provider_id: int, *, include_inactive: bool) -> list[AvailabilityRule]:
    """The provider's rules, Monday first, earliest window first.

    Raises: 404 `NOT_FOUND` if the provider is missing, or inactive and
    `include_inactive` is False.
    """
    _get_provider(db, provider_id, include_inactive=include_inactive)
    query = (
        select(AvailabilityRule)
        .where(AvailabilityRule.provider_id == provider_id)
        .order_by(AvailabilityRule.weekday, AvailabilityRule.start_time)
    )
    return list(db.scalars(query))


def _check_on_grid(start_time: time, end_time: time, granularity: int) -> None:
    for field, value in (("start_time", start_time), ("end_time", end_time)):
        if _minutes(value) % granularity:
            raise AppError(
                "MISALIGNED_TIME",
                f"{field} must be a multiple of {granularity} minutes past midnight.",
                status_code=422,
                details={"field": field, "slot_granularity_minutes": granularity},
            )


def _find_overlap(
    db: Session, provider_id: int, weekday: int, start_time: time, end_time: time, *, ignore: int
) -> AvailabilityRule | None:
    """Another rule of the provider on that weekday that shares any time with the window.

    Half-open: a rule ending exactly at `start_time` (or starting at `end_time`)
    does not overlap. `ignore` is the rule being edited (0 for a new one).
    """
    return db.scalars(
        select(AvailabilityRule)
        .where(
            AvailabilityRule.provider_id == provider_id,
            AvailabilityRule.weekday == weekday,
            AvailabilityRule.id != ignore,
            AvailabilityRule.start_time < end_time,
            AvailabilityRule.end_time > start_time,
        )
        .limit(1)
    ).first()


def _overlap_error(other: AvailabilityRule | None) -> AppError:
    details = {}
    if other is not None:
        details = {
            "conflicting_rule": {
                "id": other.id,
                "weekday": other.weekday,
                "start_time": other.start_time.isoformat(timespec="minutes"),
                "end_time": other.end_time.isoformat(timespec="minutes"),
            }
        }
    return AppError(
        "AVAILABILITY_OVERLAP",
        "This window overlaps another working window of the provider on the same weekday.",
        status_code=409,
        details=details,
    )


def _save(db: Session, rule: AvailabilityRule, other: AvailabilityRule | None) -> None:
    """Flush, turning the database's exclusion violation into `AVAILABILITY_OVERLAP`.

    The pre-check and the provider lock make this unreachable in normal use;
    it is the backstop that keeps overlaps out of the table no matter what.
    The savepoint keeps a failed flush from poisoning the whole transaction.
    """
    try:
        with db.begin_nested():
            db.add(rule)
            db.flush()
    except IntegrityError as error:
        pg = error.orig
        if getattr(pg, "sqlstate", None) == _EXCLUSION_VIOLATION and (
            getattr(getattr(pg, "diag", None), "constraint_name", None) == _OVERLAP_CONSTRAINT
        ):
            raise _overlap_error(other) from error
        raise


def _validate(db: Session, rule: AvailabilityRule, *, ignore: int) -> None:
    """Business checks for a rule about to be saved.

    Runs without autoflush: an edited rule must not be written to the database
    (and hit the exclusion constraint) before we have looked for overlaps.

    Raises: 422 `INVALID_TIME_RANGE`, 422 `MISALIGNED_TIME`, 409 `AVAILABILITY_OVERLAP`.
    """
    if rule.end_time <= rule.start_time:
        raise AppError(
            "INVALID_TIME_RANGE",
            "end_time must be later than start_time.",
            status_code=422,
        )
    with db.no_autoflush:
        _check_on_grid(
            rule.start_time, rule.end_time, get_business_settings(db).slot_granularity_minutes
        )
        other = _find_overlap(
            db, rule.provider_id, rule.weekday, rule.start_time, rule.end_time, ignore=ignore
        )
    if other is not None:
        raise _overlap_error(other)


def create_rule(db: Session, provider_id: int, data: dict[str, Any]) -> AvailabilityRule:
    """Add a weekly window to a provider.

    The provider row is locked first so two admins adding rules at once run one
    after the other, and the second sees the first in its overlap check.

    Raises:
        AppError: 404 `NOT_FOUND`; 422 `MISALIGNED_TIME`; 409 `AVAILABILITY_OVERLAP`
            (`details.conflicting_rule`).
    """
    _get_provider(db, provider_id, include_inactive=True, lock=True)
    rule = AvailabilityRule(provider_id=provider_id, **data)
    _validate(db, rule, ignore=0)
    _save(db, rule, None)
    return rule


def update_rule(
    db: Session, provider_id: int, rule_id: int, changes: dict[str, Any]
) -> AvailabilityRule:
    """Change a rule's weekday and/or times; the result is validated as a whole.

    Raises:
        AppError: 404 `NOT_FOUND`; 422 `INVALID_TIME_RANGE`, `MISALIGNED_TIME`;
            409 `AVAILABILITY_OVERLAP`.
    """
    _get_provider(db, provider_id, include_inactive=True, lock=True)
    rule = _get_rule(db, provider_id, rule_id)
    for field, value in changes.items():
        setattr(rule, field, value)
    _validate(db, rule, ignore=rule.id)
    _save(db, rule, None)
    return rule


def delete_rule(db: Session, provider_id: int, rule_id: int) -> None:
    """Remove a rule for good. Existing bookings are not touched.

    Raises: 404 `NOT_FOUND`.
    """
    _get_provider(db, provider_id, include_inactive=True, lock=True)
    db.delete(_get_rule(db, provider_id, rule_id))
    db.flush()
