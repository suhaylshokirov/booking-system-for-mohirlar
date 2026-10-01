"""The barber dashboard (P9.1): access, stats, and the pending queue's actions.

Frozen clock: Thursday 2026-10-01 07:00 UTC, 12:00 in Tashkent (UTC+5).
Jasur works Thursday and Friday 09:00-12:00 local (3 h each), so this week
(Mon 28 Sep - Sun 4 Oct) has 360 available minutes.
"""

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy.orm import Session

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import create_access_token
from app.models import (
    AvailabilityRule,
    Booking,
    BookingStatus,
    Provider,
    ProviderService,
    Service,
)
from app.models.user import User, UserRole
from app.services.booking import create_booking, transition
from app.services.dashboard import get_dashboard
from tests.support import add_barber

NOW = datetime(2026, 10, 1, 7, tzinfo=UTC)
TOMORROW_NINE = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)  # Fri 09:00 Tashkent
CSRF = "test-csrf-token"


def _user(db: Session, email: str, role=UserRole.CUSTOMER) -> User:
    user = User(email=email, password_hash="x", full_name="Test Person", role=role)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def haircut(db) -> Service:
    service = Service(name="Haircut", duration_minutes=30, price=60_000)
    db.add(service)
    db.flush()
    return service


@pytest.fixture
def jasur(db, haircut) -> Provider:
    provider = Provider(name="Jasur")
    db.add(provider)
    db.flush()
    db.add(ProviderService(provider_id=provider.id, service_id=haircut.id))
    for weekday in (3, 4):
        db.add(
            AvailabilityRule(
                provider_id=provider.id, weekday=weekday, start_time=time(9), end_time=time(12)
            )
        )
    db.flush()
    return provider


@pytest.fixture
def aziza(db) -> User:
    return _user(db, "aziza@example.com")


@pytest.fixture
def staff(db, jasur) -> User:
    """Jasur's own login: the dashboard shows his bookings and hours."""
    return add_barber(db, "staff@example.com", "Jasur", provider=jasur)


def _sign_in(client, user: User) -> None:
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, NOW))
    client.cookies.set(CSRF_COOKIE, CSRF)


def _insert(db, user, haircut, jasur, start, status) -> Booking:
    """Directly, so past and unusual bookings the rules refuse can exist."""
    booking = Booking(
        customer_id=user.id,
        provider_id=jasur.id,
        service_id=haircut.id,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        status=status,
        price_amount=60_000,
        duration_minutes=30,
    )
    db.add(booking)
    db.flush()
    return booking


def _post(client, path: str, **data):
    return client.post(path, data={"csrf_token": CSRF, **data}, follow_redirects=False)


# --- Access ----------------------------------------------------------------------------


def test_a_visitor_is_sent_to_log_in_and_back(client):
    response = client.get("/barber", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Fbarber"


def test_a_customer_sees_a_404_not_a_403(client, aziza):
    _sign_in(client, aziza)

    assert client.get("/barber").status_code == 404


def test_a_customer_cannot_confirm_a_booking(client, db, haircut, jasur, aziza):
    booking = create_booking(db, aziza, haircut.id, jasur.id, TOMORROW_NINE, None, NOW)
    _sign_in(client, aziza)

    assert _post(client, f"/barber/bookings/{booking.id}/confirm").status_code == 404
    db.refresh(booking)
    assert booking.status == BookingStatus.PENDING


# --- Stats -----------------------------------------------------------------------------


def test_stats_count_today_pending_and_the_weeks_utilization(
    client, db, haircut, jasur, aziza, staff
):
    # Today (Thu): one confirmed 09:00 and one cancelled, which must not count.
    _insert(
        db, aziza, haircut, jasur, datetime(2026, 10, 1, 4, tzinfo=UTC), BookingStatus.CONFIRMED
    )
    _insert(
        db, aziza, haircut, jasur, datetime(2026, 10, 1, 5, tzinfo=UTC), BookingStatus.CANCELLED
    )
    # Tomorrow: pending. Next Monday: outside this week.
    _insert(db, aziza, haircut, jasur, TOMORROW_NINE, BookingStatus.PENDING)
    _insert(db, aziza, haircut, jasur, datetime(2026, 10, 5, 4, tzinfo=UTC), BookingStatus.PENDING)

    result = get_dashboard(db, NOW, jasur.id)

    assert result.today_count == 1
    assert result.pending_count == 2
    assert result.booked_minutes == 60  # two non-cancelled 30-minute bookings this week
    assert result.available_minutes == 360
    assert result.utilization_percent == 17  # 60 / 360 = 16.7%


def test_utilization_is_a_dash_when_the_barber_has_no_hours(db):
    idle = Provider(name="Idle")
    db.add(idle)
    db.flush()

    result = get_dashboard(db, NOW, idle.id)

    assert result.utilization_percent is None


def test_the_page_shows_the_stats(client, db, haircut, jasur, aziza, staff):
    _insert(db, aziza, haircut, jasur, TOMORROW_NINE, BookingStatus.PENDING)
    _sign_in(client, staff)

    html = client.get("/barber").text

    assert "Bookings today" in html
    assert "8%" in html
    assert "30 of 360 min" in html


# --- The pending queue -----------------------------------------------------------------


def test_the_queue_lists_pending_bookings_and_flags_an_expired_one(
    client, db, haircut, jasur, aziza, staff
):
    _insert(db, aziza, haircut, jasur, TOMORROW_NINE, BookingStatus.PENDING)
    stale = _insert(
        db, aziza, haircut, jasur, datetime(2026, 10, 1, 4, tzinfo=UTC), BookingStatus.PENDING
    )
    _sign_in(client, staff)

    html = client.get("/barber").text

    assert "aziza@example.com" in html
    assert html.count("Expired: never confirmed") == 1
    # An expired booking can only be cleared, so it has no Confirm button.
    assert html.count("/confirm") == 1
    assert f"/barber/bookings/{stale.id}/cancel" in html


def test_confirm_moves_the_booking_to_confirmed(client, db, haircut, jasur, aziza, staff):
    booking = create_booking(db, aziza, haircut.id, jasur.id, TOMORROW_NINE, None, NOW)
    _sign_in(client, staff)

    response = _post(client, f"/barber/bookings/{booking.id}/confirm")

    assert response.status_code == 303
    assert response.headers["location"] == "/barber"
    db.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED


def test_cancel_records_the_reason(client, db, haircut, jasur, aziza, staff):
    booking = create_booking(db, aziza, haircut.id, jasur.id, TOMORROW_NINE, None, NOW)
    _sign_in(client, staff)

    response = _post(client, f"/barber/bookings/{booking.id}/cancel", reason="  Barber is ill ")

    assert response.status_code == 303
    db.refresh(booking)
    assert booking.status == BookingStatus.CANCELLED
    assert booking.cancel_reason == "Barber is ill"
    assert booking.cancelled_by_id == staff.id


def test_clearing_an_expired_pending_needs_no_reason(client, db, haircut, jasur, aziza, staff):
    stale = _insert(
        db, aziza, haircut, jasur, datetime(2026, 10, 1, 4, tzinfo=UTC), BookingStatus.PENDING
    )
    _sign_in(client, staff)

    _post(client, f"/barber/bookings/{stale.id}/cancel")

    db.refresh(stale)
    assert stale.status == BookingStatus.CANCELLED
    assert stale.cancel_reason == "not confirmed in time"


def test_a_refused_action_shows_the_reason_not_an_error_page(
    client, db, haircut, jasur, aziza, staff
):
    booking = create_booking(db, aziza, haircut.id, jasur.id, TOMORROW_NINE, None, NOW)
    transition(db, staff, booking.id, BookingStatus.CONFIRMED, NOW)
    _sign_in(client, staff)

    # Confirmed bookings need a reason to cancel (REASON_REQUIRED, 422).
    response = _post(client, f"/barber/bookings/{booking.id}/cancel")

    assert response.status_code == 422
    assert "A reason is required" in response.text
    db.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED


def test_an_unknown_booking_is_a_404(client, staff):
    _sign_in(client, staff)

    assert _post(client, "/barber/bookings/999999/confirm").status_code == 404


def test_the_dashboard_counts_only_the_barbers_own_bookings_and_hours(db, haircut, jasur, aziza):
    """Another barber's bookings, queue and hours are not Jasur's."""
    other = Provider(name="Aziz")
    db.add(other)
    db.flush()
    db.add(AvailabilityRule(provider_id=other.id, weekday=3, start_time=time(9), end_time=time(12)))
    bob = _user(db, "bob@example.com")  # a customer cannot be in two chairs at once
    _insert(db, aziza, haircut, jasur, TOMORROW_NINE, BookingStatus.PENDING)
    _insert(db, bob, haircut, other, TOMORROW_NINE, BookingStatus.PENDING)
    _insert(db, bob, haircut, other, datetime(2026, 10, 1, 4, tzinfo=UTC), BookingStatus.CONFIRMED)

    mine = get_dashboard(db, NOW, jasur.id)

    assert mine.pending_count == 1
    assert mine.today_count == 0
    assert [row.line.provider_name for row in mine.pending] == ["Jasur"]
    assert mine.available_minutes == 360  # Jasur's hours only, not Aziz's too


def test_a_deactivated_barber_has_no_available_minutes(db, jasur):
    jasur.is_active = False
    db.flush()

    assert get_dashboard(db, NOW, jasur.id).available_minutes == 0
