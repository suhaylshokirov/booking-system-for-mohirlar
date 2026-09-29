"""The seed script: a believable demo, safe to run again and again."""

from sqlalchemy import func, select

from app.core.config import Settings
from app.models import (
    AvailabilityException,
    AvailabilityRule,
    Booking,
    BookingEvent,
    BookingStatus,
    BusinessSettings,
    Provider,
    ProviderService,
    Service,
    User,
    UserRole,
)
from scripts.seed import DEMO_CUSTOMER_EMAIL, seed

TABLES = [
    User,
    BusinessSettings,
    Service,
    Provider,
    ProviderService,
    AvailabilityRule,
    AvailabilityException,
    Booking,
    BookingEvent,
]


def counts(db) -> dict[str, int]:
    return {m.__tablename__: db.scalar(select(func.count()).select_from(m)) for m in TABLES}


def test_seeding_twice_leaves_the_same_row_counts(db, frozen_clock):
    settings = Settings(admin_email="boss@example.uz", admin_password="a-long-admin-password")
    seed(db, settings, frozen_clock)
    first = counts(db)

    seed(db, settings, frozen_clock)

    assert counts(db) == first
    assert first["users"] == 2 and first["bookings"] == 4 and first["services"] == 4


def test_seed_creates_the_admin_and_a_demo_customer(db, frozen_clock):
    settings = Settings(admin_email="Boss@Example.uz", admin_password="a-long-admin-password")
    seed(db, settings, frozen_clock)

    admin = db.scalar(select(User).where(User.role == UserRole.ADMIN))
    assert admin.email == "boss@example.uz"  # stored lower-case
    assert admin.password_hash.startswith("$argon2")  # never the plain password
    assert db.scalar(select(User).where(User.email == DEMO_CUSTOMER_EMAIL)) is not None


def test_seed_covers_every_booking_status_and_keeps_history(db, frozen_clock):
    seed(db, Settings(), frozen_clock)

    statuses = set(db.scalars(select(Booking.status)))
    assert statuses == set(BookingStatus)
    # Every booking has a creation event (from_status NULL) and its last event
    # matches the booking's current status.
    for booking in db.scalars(select(Booking)):
        events = list(
            db.scalars(
                select(BookingEvent).where(BookingEvent.booking_id == booking.id).order_by("id")
            )
        )
        assert events[0].from_status is None
        assert events[-1].to_status == booking.status


def test_rerunning_the_seed_does_not_overwrite_admin_edits(db, frozen_clock):
    settings = Settings()
    seed(db, settings, frozen_clock)
    haircut = db.scalar(select(Service).where(Service.name == "Haircut"))
    haircut.price = 75_000
    haircut.is_active = False
    db.flush()

    seed(db, settings, frozen_clock)

    db.refresh(haircut)
    assert (haircut.price, haircut.is_active) == (75_000, False)
