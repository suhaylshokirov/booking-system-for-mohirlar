"""The database refuses invalid data on its own.

Every test inserts rows directly with the ORM, bypassing the service layer, so
what is proven here is what PostgreSQL guarantees even if application code has
a bug. Each expected failure runs inside a savepoint (`rejected`), which rolls
back just that statement and leaves the test's transaction usable.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AvailabilityException,
    AvailabilityRule,
    Booking,
    BookingStatus,
    Provider,
    Service,
    User,
)

EXCLUSION_VIOLATION = "23P01"
CHECK_VIOLATION = "23514"
UNIQUE_VIOLATION = "23505"

NINE = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)  # a Monday


@contextmanager
def rejected(db: Session, sqlstate: str, constraint: str):
    """Expect the block to fail with `sqlstate` naming `constraint`.

    The savepoint rolls back the failed statement only; without it Postgres
    would abort the whole test transaction.
    """
    with pytest.raises(IntegrityError) as caught:
        with db.begin_nested():
            yield
            db.flush()
    assert caught.value.orig.sqlstate == sqlstate
    assert caught.value.orig.diag.constraint_name == constraint


def make_user(db: Session, email: str = "ali@example.uz") -> User:
    user = User(email=email, password_hash="x", full_name="Ali")
    db.add(user)
    db.flush()
    return user


def make_provider(db: Session, name: str = "Jasur") -> Provider:
    provider = Provider(name=name)
    db.add(provider)
    db.flush()
    return provider


def make_service(db: Session) -> Service:
    service = Service(name="Haircut", duration_minutes=30, price=60000)
    db.add(service)
    db.flush()
    return service


def booking(
    customer: User,
    provider: Provider,
    service: Service,
    start: datetime,
    minutes: int = 30,
    status: BookingStatus = BookingStatus.PENDING,
    **overrides,
) -> Booking:
    fields = dict(
        customer_id=customer.id,
        provider_id=provider.id,
        service_id=service.id,
        start_at=start,
        end_at=start + timedelta(minutes=minutes),
        status=status,
        price_amount=service.price,
        duration_minutes=minutes,
    )
    fields.update(overrides)
    return Booking(**fields)


@pytest.fixture
def world(db: Session):
    """One customer, one provider, one service."""
    return make_user(db), make_provider(db), make_service(db)


# --- double booking ---------------------------------------------------------


def test_overlapping_booking_for_same_provider_is_rejected(db, world):
    customer, provider, service = world
    other_customer = make_user(db, "vali@example.uz")
    db.add(booking(customer, provider, service, NINE))
    db.flush()

    with rejected(db, EXCLUSION_VIOLATION, "no_provider_overlap"):
        db.add(booking(other_customer, provider, service, NINE + timedelta(minutes=15)))


def test_identical_time_for_same_provider_is_rejected(db, world):
    customer, provider, service = world
    other_customer = make_user(db, "vali@example.uz")
    db.add(booking(customer, provider, service, NINE))
    db.flush()

    with rejected(db, EXCLUSION_VIOLATION, "no_provider_overlap"):
        db.add(booking(other_customer, provider, service, NINE))


def test_overlapping_booking_for_same_customer_with_other_provider_is_rejected(db, world):
    customer, provider, service = world
    other_provider = make_provider(db, "Bekzod")
    db.add(booking(customer, provider, service, NINE))
    db.flush()

    with rejected(db, EXCLUSION_VIOLATION, "no_customer_overlap"):
        db.add(booking(customer, other_provider, service, NINE + timedelta(minutes=15)))


def test_same_time_with_different_provider_and_customer_is_allowed(db, world):
    customer, provider, service = world
    other_customer = make_user(db, "vali@example.uz")
    other_provider = make_provider(db, "Bekzod")
    db.add(booking(customer, provider, service, NINE))
    db.add(booking(other_customer, other_provider, service, NINE))
    db.flush()  # no exception


def test_back_to_back_bookings_are_allowed(db, world):
    """[10:00, 10:30) and [10:30, 11:00) touch but do not overlap."""
    customer, provider, service = world
    db.add(booking(customer, provider, service, NINE))
    db.add(booking(customer, provider, service, NINE + timedelta(minutes=30)))
    db.flush()  # no exception


@pytest.mark.parametrize("status", [BookingStatus.CANCELLED, BookingStatus.COMPLETED])
def test_cancelled_or_completed_booking_does_not_block_the_slot(db, world, status):
    customer, provider, service = world
    db.add(booking(customer, provider, service, NINE, status=status))
    db.flush()

    db.add(booking(customer, provider, service, NINE))  # same provider, same customer
    db.flush()  # no exception


@pytest.mark.parametrize("status", [BookingStatus.PENDING, BookingStatus.CONFIRMED])
def test_pending_and_confirmed_bookings_both_block_the_slot(db, world, status):
    customer, provider, service = world
    other_customer = make_user(db, "vali@example.uz")
    db.add(booking(customer, provider, service, NINE, status=status))
    db.flush()

    with rejected(db, EXCLUSION_VIOLATION, "no_provider_overlap"):
        db.add(booking(other_customer, provider, service, NINE))


def test_cancelling_a_booking_frees_its_slot(db, world):
    customer, provider, service = world
    other_customer = make_user(db, "vali@example.uz")
    first = booking(customer, provider, service, NINE, status=BookingStatus.CONFIRMED)
    db.add(first)
    db.flush()

    first.status = BookingStatus.CANCELLED
    first.cancelled_by_id = customer.id
    db.flush()

    db.add(booking(other_customer, provider, service, NINE))
    db.flush()  # no exception


# --- availability rules -----------------------------------------------------


def rule(provider: Provider, weekday: int, start: time, end: time) -> AvailabilityRule:
    return AvailabilityRule(
        provider_id=provider.id, weekday=weekday, start_time=start, end_time=end
    )


def test_overlapping_availability_rules_are_rejected(db):
    provider = make_provider(db)
    db.add(rule(provider, 0, time(9), time(13)))
    db.flush()

    with rejected(db, EXCLUSION_VIOLATION, "no_availability_rule_overlap"):
        db.add(rule(provider, 0, time(12, 30), time(14)))


def test_adjacent_availability_rules_are_allowed(db):
    provider = make_provider(db)
    db.add(rule(provider, 0, time(9), time(13)))
    db.add(rule(provider, 0, time(13), time(18)))
    db.flush()  # no exception


def test_same_hours_on_another_weekday_or_provider_are_allowed(db):
    provider = make_provider(db)
    other_provider = make_provider(db, "Bekzod")
    db.add(rule(provider, 0, time(9), time(13)))
    db.add(rule(provider, 1, time(9), time(13)))
    db.add(rule(other_provider, 0, time(9), time(13)))
    db.flush()  # no exception


# --- CHECK constraints ------------------------------------------------------


def test_booking_ending_at_or_before_its_start_is_rejected(db, world):
    customer, provider, service = world
    with rejected(db, CHECK_VIOLATION, "ck_bookings_end_after_start"):
        db.add(booking(customer, provider, service, NINE, end_at=NINE))
    with rejected(db, CHECK_VIOLATION, "ck_bookings_end_after_start"):
        db.add(booking(customer, provider, service, NINE, end_at=NINE - timedelta(minutes=1)))


def test_negative_service_price_is_rejected(db):
    with rejected(db, CHECK_VIOLATION, "ck_services_price_not_negative"):
        db.add(Service(name="Haircut", duration_minutes=30, price=-1))


def test_free_service_is_allowed(db):
    db.add(Service(name="Consultation", duration_minutes=15, price=0))
    db.flush()  # no exception


@pytest.mark.parametrize("minutes", [0, -30])
def test_zero_or_negative_service_duration_is_rejected(db, minutes):
    with rejected(db, CHECK_VIOLATION, "ck_services_duration_positive"):
        db.add(Service(name="Haircut", duration_minutes=minutes, price=60000))


def test_negative_booking_price_snapshot_is_rejected(db, world):
    customer, provider, service = world
    with rejected(db, CHECK_VIOLATION, "ck_bookings_price_not_negative"):
        db.add(booking(customer, provider, service, NINE, price_amount=-1))


def test_zero_booking_duration_snapshot_is_rejected(db, world):
    customer, provider, service = world
    with rejected(db, CHECK_VIOLATION, "ck_bookings_duration_positive"):
        db.add(booking(customer, provider, service, NINE, duration_minutes=0))


@pytest.mark.parametrize("weekday", [-1, 7])
def test_weekday_outside_0_to_6_is_rejected(db, weekday):
    provider = make_provider(db)
    with rejected(db, CHECK_VIOLATION, "ck_availability_rules_weekday_range"):
        db.add(rule(provider, weekday, time(9), time(13)))


@pytest.mark.parametrize("end", [time(9), time(8)])
def test_availability_rule_ending_at_or_before_its_start_is_rejected(db, end):
    provider = make_provider(db)
    with rejected(db, CHECK_VIOLATION, "ck_availability_rules_end_after_start"):
        db.add(rule(provider, 0, time(9), end))


def test_exception_needs_both_times_or_neither(db):
    provider = make_provider(db)
    day = datetime(2026, 10, 6).date()
    with rejected(db, CHECK_VIOLATION, "ck_availability_exceptions_day_off_or_valid_hours"):
        db.add(AvailabilityException(provider_id=provider.id, date=day, start_time=time(10)))
    with rejected(db, CHECK_VIOLATION, "ck_availability_exceptions_day_off_or_valid_hours"):
        db.add(
            AvailabilityException(
                provider_id=provider.id, date=day, start_time=time(12), end_time=time(10)
            )
        )


def test_exception_day_off_and_custom_hours_are_allowed(db):
    provider = make_provider(db)
    db.add(AvailabilityException(provider_id=provider.id, date=datetime(2026, 10, 6).date()))
    db.add(
        AvailabilityException(
            provider_id=provider.id,
            date=datetime(2026, 10, 7).date(),
            start_time=time(10),
            end_time=time(14),
        )
    )
    db.flush()  # no exception


def test_second_exception_for_the_same_provider_and_date_is_rejected(db):
    provider = make_provider(db)
    day = datetime(2026, 10, 6).date()
    db.add(AvailabilityException(provider_id=provider.id, date=day))
    db.flush()
    with rejected(db, UNIQUE_VIOLATION, "uq_availability_exceptions_provider_date"):
        db.add(AvailabilityException(provider_id=provider.id, date=day))


def test_cancellation_details_on_a_live_booking_are_rejected(db, world):
    customer, provider, service = world
    with rejected(db, CHECK_VIOLATION, "ck_bookings_cancellation_fields_only_when_cancelled"):
        db.add(booking(customer, provider, service, NINE, cancel_reason="changed my mind"))


def test_second_business_settings_row_is_rejected(db):
    from app.models import BusinessSettings

    db.add(BusinessSettings(name="Navbat Barbershop"))
    db.flush()
    with rejected(db, CHECK_VIOLATION, "ck_business_settings_single_row"):
        db.add(BusinessSettings(id=2, name="Second"))


# --- users ------------------------------------------------------------------


def test_duplicate_email_differing_only_in_case_is_rejected(db):
    make_user(db, "Ali@Example.uz")
    with rejected(db, UNIQUE_VIOLATION, "uq_users_email_lower"):
        db.add(User(email="ali@example.UZ", password_hash="x", full_name="Other"))


# --- history is protected ---------------------------------------------------


def test_referenced_service_cannot_be_hard_deleted(db, world):
    """`ON DELETE RESTRICT`: services with bookings are deactivated, not deleted."""
    customer, provider, service = world
    db.add(booking(customer, provider, service, NINE))
    db.flush()

    with pytest.raises(IntegrityError) as caught:
        with db.begin_nested():
            db.delete(service)
            db.flush()
    assert caught.value.orig.sqlstate == "23503"  # foreign_key_violation


def test_booking_keeps_its_snapshot_when_the_service_changes(db, world):
    """The snapshot columns are independent of the service row (ADR 0007)."""
    customer, provider, service = world
    saved = booking(customer, provider, service, NINE)
    db.add(saved)
    db.flush()

    service.price = 90000
    service.duration_minutes = 45
    db.flush()
    db.refresh(saved)

    assert (saved.price_amount, saved.duration_minutes) == (60000, 30)
