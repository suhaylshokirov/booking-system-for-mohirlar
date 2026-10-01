"""Seed a believable demo barbershop: `python -m scripts.seed`.

Idempotent: every block first looks for what it would create and skips it if
it is already there, so running the seed twice leaves the same rows and never
overwrites edits made in the barber UI (a changed price stays changed).

Creates business settings (Asia/Tashkent, UZS, 15-minute slots), four
services, three barbers with different service sets and weekly hours, one
day off, a login for each barber (the first is BARBER_EMAIL, all share
BARBER_PASSWORD), a demo customer, and
four bookings in different statuses with their history events.

The bookings are inserted directly rather than through the booking service:
the seed is trusted data, and it must not depend on the lead-time and horizon
rules (it creates a past, completed booking). The exclusion constraints still
apply. Dates are relative to today so the demo always has upcoming bookings.
"""

from datetime import date, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.core.timezones import local_to_utc, utc_to_local
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

Status = BookingStatus  # short alias: the histories below stay readable

DEMO_CUSTOMER_EMAIL = "demo@navbat.local"
DEMO_CUSTOMER_PASSWORD = "demo-customer-password"
BUSINESS_NAME = "Navbat Barbershop"
TIMEZONE = "Asia/Tashkent"

# name, description, minutes, price in UZS
SERVICES = [
    ("Haircut", "Classic scissor or clipper cut with a wash and style.", 30, 60_000),
    ("Beard trim", "Shape and trim with a hot towel finish.", 20, 40_000),
    ("Haircut + beard", "The full treatment: cut, beard trim and styling.", 45, 90_000),
    ("Kids haircut", "For children under 12.", 30, 45_000),
]

# barber -> (services offered, weekdays worked 0=Mon, [(start, end), ...])
MON_SAT = [0, 1, 2, 3, 4, 5]
BARBERS = {
    "Jasur": (
        ["Haircut", "Beard trim", "Haircut + beard", "Kids haircut"],
        MON_SAT,
        [(time(9), time(13)), (time(14), time(19))],  # lunch break 13:00-14:00
    ),
    "Bekzod": (
        ["Haircut", "Beard trim", "Haircut + beard"],
        [0, 1, 2, 3, 4],
        [(time(10), time(18))],
    ),
    "Dilshod": (
        ["Haircut", "Kids haircut"],
        [1, 2, 3, 4, 5],
        [(time(9), time(17))],
    ),
}


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def seed_business_settings(db: Session) -> None:
    if db.get(BusinessSettings, 1) is None:
        db.add(BusinessSettings(id=1, name=BUSINESS_NAME, timezone=TIMEZONE, currency="UZS"))
        db.flush()


def seed_services(db: Session) -> dict[str, Service]:
    for name, description, minutes, price in SERVICES:
        if db.scalar(select(Service).where(Service.name == name)) is None:
            db.add(
                Service(name=name, description=description, duration_minutes=minutes, price=price)
            )
    db.flush()
    return {s.name: s for s in db.scalars(select(Service))}


def seed_providers(db: Session, services: dict[str, Service]) -> dict[str, Provider]:
    """Providers, the services each offers, and their weekly hours."""
    providers: dict[str, Provider] = {}
    for name, (offered, weekdays, windows) in BARBERS.items():
        provider = db.scalar(select(Provider).where(Provider.name == name))
        if provider is None:
            provider = Provider(name=name)
            db.add(provider)
            db.flush()
            for service_name in offered:
                db.add(
                    ProviderService(provider_id=provider.id, service_id=services[service_name].id)
                )
            for weekday in weekdays:
                for start, end in windows:
                    db.add(
                        AvailabilityRule(
                            provider_id=provider.id, weekday=weekday, start_time=start, end_time=end
                        )
                    )
        providers[name] = provider
    db.flush()
    return providers


def seed_day_off(db: Session, provider: Provider, today: date) -> None:
    """Bekzod takes one weekday off in about a week, to show an exception."""
    day = _working_day(BARBERS[provider.name][1], today + timedelta(days=7))
    exists = db.scalar(
        select(AvailabilityException).where(
            AvailabilityException.provider_id == provider.id,
            AvailabilityException.date == day,
        )
    )
    if exists is None and _count(db, AvailabilityException) == 0:
        db.add(AvailabilityException(provider_id=provider.id, date=day, reason="Day off"))
        db.flush()


def seed_user(
    db: Session,
    email: str,
    password: str,
    full_name: str,
    role: UserRole,
    provider: Provider | None = None,
) -> User:
    """Create the user if missing. An existing user is left untouched.

    A barber is given their `provider` (the database requires it).
    """
    user = db.scalar(select(User).where(func.lower(User.email) == email.lower()))
    if user is None:
        user = User(
            email=email.lower(),
            password_hash=hash_password(password),
            full_name=full_name,
            role=role,
            provider_id=provider.id if provider else None,
        )
        db.add(user)
        db.flush()
    return user


def seed_barbers(
    db: Session, settings: Settings, providers: dict[str, Provider]
) -> dict[str, User]:
    """One login per barber. The first is BARBER_EMAIL; the rest are `name@navbat.local`."""
    barbers = {}
    for index, (name, provider) in enumerate(providers.items()):
        email = settings.barber_email if index == 0 else f"{name.lower()}@navbat.local"
        barbers[name] = seed_user(
            db, email, settings.barber_password, name, UserRole.BARBER, provider
        )
    return barbers


def _working_day(weekdays: list[int], start: date, step: int = 1) -> date:
    """The first date from `start` (going forward or, with step=-1, back) on a working weekday."""
    day = start
    while day.weekday() not in weekdays:
        day += timedelta(days=step)
    return day


def _add_booking(
    db: Session,
    *,
    customer: User,
    provider: Provider,
    service: Service,
    day: date,
    at: time,
    history: list[tuple[BookingStatus, User, str | None]],
    notes: str | None = None,
) -> None:
    """Insert a booking whose final status is the last entry of `history`.

    Each `history` entry is (status reached, who did it, reason) and becomes a
    `booking_events` row; the first entry is the creation.
    """
    start = local_to_utc(day, at, TIMEZONE)
    final_status, final_actor, final_reason = history[-1]
    cancelled = final_status == BookingStatus.CANCELLED
    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_id=service.id,
        start_at=start,
        end_at=start + timedelta(minutes=service.duration_minutes),
        status=final_status,
        price_amount=service.price,
        duration_minutes=service.duration_minutes,
        notes=notes,
        cancelled_by_id=final_actor.id if cancelled else None,
        cancel_reason=final_reason if cancelled else None,
    )
    db.add(booking)
    db.flush()
    previous: BookingStatus | None = None
    for status, actor, reason in history:
        db.add(
            BookingEvent(
                booking_id=booking.id,
                from_status=previous,
                to_status=status,
                actor_id=actor.id,
                reason=reason,
            )
        )
        previous = status
    db.flush()


def seed_bookings(
    db: Session,
    today: date,
    customer: User,
    barbers: dict[str, User],
    providers: dict[str, Provider],
    services: dict[str, Service],
) -> None:
    """Four bookings for the demo customer, only if the shop has none yet."""
    if _count(db, Booking) > 0:
        return
    P, S = providers, services
    days = {name: BARBERS[name][1] for name in BARBERS}

    _add_booking(  # a finished visit, so history has a Completed entry
        db,
        customer=customer,
        provider=P["Jasur"],
        service=S["Haircut"],
        day=_working_day(days["Jasur"], today - timedelta(days=2), step=-1),
        at=time(10),
        history=[
            (Status.PENDING, customer, None),
            (Status.CONFIRMED, barbers["Jasur"], None),
            (Status.COMPLETED, barbers["Jasur"], None),
        ],
    )
    _add_booking(  # upcoming and confirmed
        db,
        customer=customer,
        provider=P["Jasur"],
        service=S["Haircut + beard"],
        day=_working_day(days["Jasur"], today + timedelta(days=1)),
        at=time(11),
        history=[(Status.PENDING, customer, None), (Status.CONFIRMED, barbers["Jasur"], None)],
        notes="Please use the small clipper guard.",
    )
    _add_booking(  # upcoming, waiting for Bekzod
        db,
        customer=customer,
        provider=P["Bekzod"],
        service=S["Beard trim"],
        day=_working_day(days["Bekzod"], today + timedelta(days=2)),
        at=time(15),
        history=[(Status.PENDING, customer, None)],
    )
    _add_booking(  # cancelled by the customer, so its slot is free again
        db,
        customer=customer,
        provider=P["Dilshod"],
        service=S["Haircut"],
        day=_working_day(days["Dilshod"], today + timedelta(days=3)),
        at=time(10),
        history=[(Status.PENDING, customer, None), (Status.CANCELLED, customer, "Change of plans")],
    )


def seed(db: Session, settings: Settings, clock: Clock) -> None:
    """Seed everything. Does not commit; the caller decides."""
    # "Today" on the shop's wall clock, not UTC's: after 19:00 UTC it is
    # already tomorrow in Tashkent.
    today = utc_to_local(clock.now(), TIMEZONE).date()
    seed_business_settings(db)
    services = seed_services(db)
    providers = seed_providers(db, services)
    seed_day_off(db, providers["Bekzod"], today)
    barbers = seed_barbers(db, settings, providers)
    customer = seed_user(
        db, DEMO_CUSTOMER_EMAIL, DEMO_CUSTOMER_PASSWORD, "Demo Customer", UserRole.CUSTOMER
    )
    seed_bookings(db, today, customer, barbers, providers, services)


def main() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        seed(db, settings, SystemClock())
        db.commit()
    print("Seed complete.")


if __name__ == "__main__":
    main()
