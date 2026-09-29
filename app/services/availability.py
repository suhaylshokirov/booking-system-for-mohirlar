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

Exceptions override one date:
* An exception for a date **replaces** that date's weekly rules: either closed
  (no times) or one custom window, on the same slot grid as rules.
* One exception per provider per date. Checked here for a friendly message and
  enforced by the unique constraint as the backstop.
* "Today" is the current date in the *business* timezone, not in UTC: a date is
  in the past once it has ended on the business's wall clock. Past dates cannot
  be created or edited (they can be deleted).
* Exceptions never modify bookings, even ones on that date.
"""

from collections.abc import Callable
from datetime import date, time
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import Clock
from app.core.errors import AppError
from app.core.timezones import utc_to_local
from app.models.availability import AvailabilityException, AvailabilityRule
from app.models.provider import Provider
from app.services.business_settings import get_business_settings

_OVERLAP_CONSTRAINT = "no_availability_rule_overlap"
_EXCEPTION_DATE_CONSTRAINT = "uq_availability_exceptions_provider_date"


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


def _save(db: Session, row: Any, *, on_violation: dict[str, Callable[[], AppError]]) -> None:
    """Flush `row`, turning a violation of a known constraint into its friendly error.

    The pre-checks and the provider lock make these unreachable in normal use;
    the constraints are the backstop that keeps bad rows out of the table no
    matter what. The savepoint keeps a failed flush from poisoning the whole
    transaction.
    """
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
    except IntegrityError as error:
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        if constraint in on_violation:
            raise on_violation[constraint]() from error
        raise


def _check_window(db: Session, start_time: time, end_time: time) -> None:
    """A window must end after it starts and sit on the slot grid.

    Raises: 422 `INVALID_TIME_RANGE`, 422 `MISALIGNED_TIME`.
    """
    if end_time <= start_time:
        raise AppError(
            "INVALID_TIME_RANGE", "end_time must be later than start_time.", status_code=422
        )
    _check_on_grid(start_time, end_time, get_business_settings(db).slot_granularity_minutes)


def _validate(db: Session, rule: AvailabilityRule, *, ignore: int) -> None:
    """Business checks for a rule about to be saved.

    Runs without autoflush: an edited rule must not be written to the database
    (and hit the exclusion constraint) before we have looked for overlaps.

    Raises: 422 `INVALID_TIME_RANGE`, 422 `MISALIGNED_TIME`, 409 `AVAILABILITY_OVERLAP`.
    """
    with db.no_autoflush:
        _check_window(db, rule.start_time, rule.end_time)
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
    _save(db, rule, on_violation={_OVERLAP_CONSTRAINT: lambda: _overlap_error(None)})
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
    _save(db, rule, on_violation={_OVERLAP_CONSTRAINT: lambda: _overlap_error(None)})
    return rule


def delete_rule(db: Session, provider_id: int, rule_id: int) -> None:
    """Remove a rule for good. Existing bookings are not touched.

    Raises: 404 `NOT_FOUND`.
    """
    _get_provider(db, provider_id, include_inactive=True, lock=True)
    db.delete(_get_rule(db, provider_id, rule_id))
    db.flush()


# --- exceptions --------------------------------------------------------------


def _get_exception(db: Session, provider_id: int, exception_id: int) -> AvailabilityException:
    """An exception of *this* provider; another provider's id is just as missing."""
    row = db.scalars(
        select(AvailabilityException).where(
            AvailabilityException.id == exception_id,
            AvailabilityException.provider_id == provider_id,
        )
    ).one_or_none()
    if row is None:
        raise AppError("NOT_FOUND", "Availability exception not found.", status_code=404)
    return row


def _exception_exists_error(existing_id: int | None) -> AppError:
    return AppError(
        "AVAILABILITY_EXCEPTION_EXISTS",
        "This provider already has an exception for that date; change or delete it instead.",
        status_code=409,
        details={} if existing_id is None else {"exception_id": existing_id},
    )


def _find_exception_on(db: Session, provider_id: int, day: date, *, ignore: int) -> int | None:
    """The id of another exception of the provider for `day`, if there is one."""
    return db.scalars(
        select(AvailabilityException.id).where(
            AvailabilityException.provider_id == provider_id,
            AvailabilityException.date == day,
            AvailabilityException.id != ignore,
        )
    ).first()


def _validate_exception(
    db: Session, row: AvailabilityException, clock: Clock, *, ignore: int
) -> None:
    """Business checks for an exception about to be saved.

    Raises: 422 `DATE_IN_PAST`, 422 `INVALID_TIME_RANGE`, 422 `MISALIGNED_TIME`,
    409 `AVAILABILITY_EXCEPTION_EXISTS`.
    """
    with db.no_autoflush:
        settings = get_business_settings(db)
        today = utc_to_local(clock.now(), settings.timezone).date()
        if row.date < today:
            raise AppError(
                "DATE_IN_PAST",
                f"{row.date.isoformat()} is before today ({today.isoformat()}) in the "
                "business timezone.",
                status_code=422,
                details={"today": today.isoformat(), "timezone": settings.timezone},
            )
        if (row.start_time is None) != (row.end_time is None):
            raise AppError(
                "INVALID_TIME_RANGE",
                "Set both start_time and end_time, or neither for a day off.",
                status_code=422,
            )
        if row.start_time is not None:
            _check_window(db, row.start_time, row.end_time)
        existing = _find_exception_on(db, row.provider_id, row.date, ignore=ignore)
    if existing is not None:
        raise _exception_exists_error(existing)


def list_exceptions(db: Session, provider_id: int) -> list[AvailabilityException]:
    """All of the provider's exceptions, earliest date first (past ones included).

    Raises: 404 `NOT_FOUND`.
    """
    _get_provider(db, provider_id, include_inactive=True)
    return list(
        db.scalars(
            select(AvailabilityException)
            .where(AvailabilityException.provider_id == provider_id)
            .order_by(AvailabilityException.date)
        )
    )


def create_exception(
    db: Session, provider_id: int, data: dict[str, Any], clock: Clock
) -> AvailabilityException:
    """Close a date, or give it custom hours, replacing the weekly rules for it.

    Bookings already made for that date are kept as they are.

    Raises:
        AppError: 404 `NOT_FOUND`; 422 `DATE_IN_PAST`, `INVALID_TIME_RANGE`,
            `MISALIGNED_TIME`; 409 `AVAILABILITY_EXCEPTION_EXISTS`.
    """
    _get_provider(db, provider_id, include_inactive=True, lock=True)
    row = AvailabilityException(provider_id=provider_id, **data)
    _validate_exception(db, row, clock, ignore=0)
    _save(db, row, on_violation={_EXCEPTION_DATE_CONSTRAINT: lambda: _exception_exists_error(None)})
    return row


def update_exception(
    db: Session, provider_id: int, exception_id: int, changes: dict[str, Any], clock: Clock
) -> AvailabilityException:
    """Change an exception; the result is validated as a whole.

    Both times set to null turns the date into a day off. An exception whose
    date has already passed cannot be edited (only deleted).

    Raises:
        AppError: 404 `NOT_FOUND`; 422 `DATE_IN_PAST`, `INVALID_TIME_RANGE`,
            `MISALIGNED_TIME`; 409 `AVAILABILITY_EXCEPTION_EXISTS`.
    """
    _get_provider(db, provider_id, include_inactive=True, lock=True)
    row = _get_exception(db, provider_id, exception_id)
    for field, value in changes.items():
        setattr(row, field, value)
    _validate_exception(db, row, clock, ignore=row.id)
    _save(db, row, on_violation={_EXCEPTION_DATE_CONSTRAINT: lambda: _exception_exists_error(None)})
    return row


def delete_exception(db: Session, provider_id: int, exception_id: int) -> None:
    """Remove an exception, so the weekly rules apply to that date again.

    Raises: 404 `NOT_FOUND`.
    """
    _get_provider(db, provider_id, include_inactive=True, lock=True)
    db.delete(_get_exception(db, provider_id, exception_id))
    db.flush()
