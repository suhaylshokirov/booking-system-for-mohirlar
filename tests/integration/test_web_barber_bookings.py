"""Barber bookings pages (P9.5): filters, pages, actions, detail and history.

A barber sees and acts on the bookings made with them only; another barber's are 404.

Frozen clock: Thursday 2026-10-01 07:00 UTC, 12:00 in Tashkent.
"""

from datetime import UTC, datetime, time, timedelta

import pytest

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
from tests.integration.test_web_barber_dashboard import NOW
from tests.support import add_barber

CSRF = "test-csrf-token"
FRIDAY_NINE = datetime(2026, 10, 2, 4, tzinfo=UTC)  # 09:00 Tashkent


def _user(db, email, role=UserRole.CUSTOMER, name="Test Person") -> User:
    user = User(email=email, password_hash="x", full_name=name, role=role)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def staff(db, jasur) -> User:
    """Jasur's own login (named "Owner Person" so history lines are easy to find)."""
    return add_barber(db, "staff@example.com", "Owner Person", provider=jasur)


@pytest.fixture
def aziza(db) -> User:
    return _user(db, "aziza@example.com", name="Aziza")


@pytest.fixture
def bob(db) -> User:
    return _user(db, "bob@example.org", name="Bob")


@pytest.fixture
def haircut(db) -> Service:
    service = Service(name="Haircut", duration_minutes=30, price=60_000)
    db.add(service)
    db.flush()
    return service


def _provider(db, name, haircut) -> Provider:
    provider = Provider(name=name)
    db.add(provider)
    db.flush()
    db.add(ProviderService(provider_id=provider.id, service_id=haircut.id))
    db.add(
        AvailabilityRule(provider_id=provider.id, weekday=4, start_time=time(9), end_time=time(12))
    )
    db.flush()
    return provider


@pytest.fixture
def jasur(db, haircut) -> Provider:
    return _provider(db, "Jasur", haircut)


@pytest.fixture
def ali(db, haircut) -> Provider:
    """Another barber's provider: bookings with Ali are not Jasur's to see."""
    return _provider(db, "Ali", haircut)


def _sign_in(client, user) -> None:
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, NOW))
    client.cookies.set(CSRF_COOKIE, CSRF)


def _post(client, path, **data):
    return client.post(path, data={"csrf_token": CSRF, **data}, follow_redirects=False)


def _insert(db, customer, provider, haircut, start, status=BookingStatus.PENDING) -> Booking:
    """Directly, so past and unusual bookings the rules refuse can exist."""
    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
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


# --- Access ----------------------------------------------------------------------------


def test_a_customer_gets_404_and_a_visitor_a_login_redirect(client, db, aziza, haircut, jasur):
    booking = create_booking(db, aziza, haircut.id, jasur.id, FRIDAY_NINE, None, NOW)
    assert client.get("/barber/bookings", follow_redirects=False).status_code == 303
    _sign_in(client, aziza)

    assert client.get("/barber/bookings").status_code == 404
    assert client.get(f"/barber/bookings/{booking.id}").status_code == 404


# --- The list and its filters ------------------------------------------------------------


@pytest.fixture
def three(db, staff, aziza, bob, haircut, jasur, ali):
    """Jasur's: Aziza pending Fri 09:00; Bob confirmed Fri 09:30; Aziza cancelled Sat."""
    return (
        _insert(db, aziza, jasur, haircut, FRIDAY_NINE),
        _insert(
            db, bob, jasur, haircut, FRIDAY_NINE + timedelta(minutes=30), BookingStatus.CONFIRMED
        ),
        _insert(
            db, aziza, jasur, haircut, FRIDAY_NINE + timedelta(days=1), BookingStatus.CANCELLED
        ),
    )


@pytest.fixture
def elsewhere(db, bob, haircut, ali) -> Booking:
    """A booking made with the other barber."""
    return _insert(db, bob, ali, haircut, FRIDAY_NINE + timedelta(hours=2))


def _ids_on(html: str, bookings) -> list[bool]:
    return [f'href="/barber/bookings/{b.id}"' in html for b in bookings]


def test_the_list_shows_the_barbers_bookings_with_status_in_words(client, staff, three, elsewhere):
    _sign_in(client, staff)

    html = client.get("/barber/bookings").text

    assert _ids_on(html, three) == [True, True, True]
    assert _ids_on(html, [elsewhere]) == [False]  # another barber's booking never appears
    assert "3 bookings" in html
    for word in ("Pending", "Confirmed", "Cancelled"):
        assert word in html


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("status=pending", [True, False, False]),
        ("status=confirmed", [False, True, False]),
        ("customer=AZIZA", [True, False, True]),  # part of the email, any case
        ("customer=example.org", [False, True, False]),
        ("date_from=2026-10-03", [False, False, True]),  # Saturday
        ("date_to=2026-10-02", [True, True, False]),
        ("date_from=2026-10-02&date_to=2026-10-02&status=confirmed", [False, True, False]),
        ("status=nonsense&date_from=garbage", [True, True, True]),  # ignored, not an error
    ],
)
def test_filters_narrow_the_list(client, staff, three, query, expected):
    _sign_in(client, staff)

    html = client.get("/barber/bookings?" + query).text

    assert _ids_on(html, three) == expected


def test_a_percent_in_the_email_filter_is_not_a_wildcard(client, staff, three):
    _sign_in(client, staff)

    html = client.get("/barber/bookings?customer=%25").text

    assert _ids_on(html, three) == [False, False, False]
    assert "No bookings match" in html


def test_the_live_filter_gets_only_the_table(client, staff, three):
    _sign_in(client, staff)

    fragment = client.get("/barber/bookings?status=pending", headers={"X-Requested-With": "fetch"})

    assert fragment.status_code == 200
    assert "<html" not in fragment.text
    assert "1 booking" in fragment.text


def test_pages_keep_the_filters(client, db, staff, aziza, haircut, jasur):
    for i in range(21):
        _insert(db, aziza, jasur, haircut, FRIDAY_NINE + timedelta(hours=i + 1))
    _sign_in(client, staff)

    html = client.get("/barber/bookings?status=pending").text

    assert "Page 1 of 2" in html
    assert "status=pending&amp;page=2" in html
    assert client.get("/barber/bookings?status=pending&page=2").status_code == 200
    assert client.get("/barber/bookings?page=3").status_code == 404


# --- Actions ---------------------------------------------------------------------------


def test_confirm_from_the_list_returns_to_the_list(client, db, staff, three):
    _sign_in(client, staff)

    response = _post(
        client, f"/barber/bookings/{three[0].id}/confirm", next="/barber/bookings?status=pending"
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/barber/bookings?status=pending"
    db.refresh(three[0])
    assert three[0].status == BookingStatus.CONFIRMED


def test_next_cannot_leave_the_site(client, staff, three):
    _sign_in(client, staff)

    response = _post(client, f"/barber/bookings/{three[0].id}/confirm", next="https://evil.example")

    assert response.headers["location"] == "/"


def test_complete_after_the_booking_ended(client, db, staff, aziza, haircut, jasur):
    past = _insert(
        db, aziza, jasur, haircut, datetime(2026, 9, 30, 5, tzinfo=UTC), BookingStatus.CONFIRMED
    )
    _sign_in(client, staff)
    assert "Mark completed" in client.get("/barber/bookings?status=confirmed").text

    response = _post(client, f"/barber/bookings/{past.id}/complete", next="/barber/bookings")

    assert response.status_code == 303
    db.refresh(past)
    assert past.status == BookingStatus.COMPLETED


def test_completing_before_the_end_shows_the_reason_and_changes_nothing(client, db, staff, three):
    confirmed = three[1]  # tomorrow, not over
    _sign_in(client, staff)
    assert "Mark completed" not in client.get("/barber/bookings").text  # no button yet

    response = _post(client, f"/barber/bookings/{confirmed.id}/complete", next="/barber/bookings")

    assert response.status_code == 409
    assert "can only be completed after it ends" in response.text
    db.refresh(confirmed)
    assert confirmed.status == BookingStatus.CONFIRMED


def test_cancelling_a_confirmed_booking_needs_a_reason(client, db, staff, three):
    confirmed = three[1]
    _sign_in(client, staff)

    refused = _post(client, f"/barber/bookings/{confirmed.id}/cancel", next="/barber/bookings")
    assert refused.status_code == 422
    assert "A reason is required" in refused.text

    done = _post(
        client,
        f"/barber/bookings/{confirmed.id}/cancel",
        reason="Barber ill",
        next="/barber/bookings",
    )
    assert done.status_code == 303
    db.refresh(confirmed)
    assert (confirmed.status, confirmed.cancel_reason) == (BookingStatus.CANCELLED, "Barber ill")


def test_a_finished_booking_has_no_action_buttons(client, staff, three):
    _sign_in(client, staff)

    html = client.get(f"/barber/bookings/{three[2].id}").text  # the cancelled one

    assert "/cancel" not in html and "/confirm" not in html


# --- Detail ----------------------------------------------------------------------------


def test_detail_shows_the_customer_and_the_full_history(client, db, staff, aziza, haircut, jasur):
    booking = create_booking(db, aziza, haircut.id, jasur.id, FRIDAY_NINE, None, NOW)
    transition(db, staff, booking.id, BookingStatus.CONFIRMED, NOW)
    transition(db, staff, booking.id, BookingStatus.CANCELLED, NOW, "Barber ill")
    _sign_in(client, staff)

    html = client.get(f"/barber/bookings/{booking.id}").text

    assert "aziza@example.com" in html
    assert "Requested (by Aziza)" in html
    assert "Pending → confirmed by Owner Person" in html
    assert "Confirmed → cancelled by Owner Person" in html
    assert "Reason: Barber ill" in html


def test_an_unknown_booking_is_404(client, staff):
    _sign_in(client, staff)

    assert client.get("/barber/bookings/999999").status_code == 404


def test_another_barbers_booking_is_a_404_page_and_cannot_be_acted_on(client, db, staff, elsewhere):
    _sign_in(client, staff)

    assert client.get(f"/barber/bookings/{elsewhere.id}").status_code == 404
    for action in ("confirm", "cancel", "complete"):
        response = _post(client, f"/barber/bookings/{elsewhere.id}/{action}", reason="x")
        assert response.status_code == 404, action
    db.refresh(elsewhere)
    assert elsewhere.status == BookingStatus.PENDING
