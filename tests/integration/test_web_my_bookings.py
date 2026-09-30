"""My bookings in the browser: the list, one booking, and Cancel (P8.5).

Frozen clock: Thursday 2026-10-01 07:00 UTC, 12:00 in Tashkent (UTC+5).
Jasur works Friday 2026-10-02 09:00-12:00 local (04:00-07:00 UTC).
Default settings: 2-hour cancellation cutoff, so a confirmed 09:00 booking can
be cancelled online until 07:00 local, 02:00 UTC.
"""

from datetime import UTC, datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import create_access_token
from app.models import (
    AvailabilityRule,
    Booking,
    BookingEvent,
    BookingStatus,
    Provider,
    ProviderService,
    Service,
)
from app.models.user import User, UserRole
from app.services.booking import create_booking, transition
from app.web.formatting import NBSP
from app.web.templating import FLASH_COOKIE

NOW = datetime(2026, 10, 1, 7, tzinfo=UTC)
NINE = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)  # 09:00 Tashkent
TEN = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)
CSRF = "test-csrf-token"


def _user(db: Session, email: str, role=UserRole.CUSTOMER) -> User:
    user = User(email=email, password_hash="x", full_name="Test Person", role=role)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def haircut(db: Session) -> Service:
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
    db.add(
        AvailabilityRule(provider_id=provider.id, weekday=4, start_time=time(9), end_time=time(12))
    )
    db.flush()
    return provider


@pytest.fixture
def aziza(db) -> User:
    return _user(db, "aziza@example.com")


@pytest.fixture
def bob(db) -> User:
    return _user(db, "bob@example.com")


@pytest.fixture
def staff(db) -> User:
    return _user(db, "staff@example.com", UserRole.ADMIN)


def _sign_in(client, user: User, at: datetime = NOW) -> None:
    """Cookies as the browser holds them; `at` matters once a test moves the clock,
    because the access token expires."""
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, at))
    client.cookies.set(CSRF_COOKIE, CSRF)


def _book(db, user, haircut, jasur, start=NINE) -> Booking:
    return create_booking(db, user, haircut.id, jasur.id, start, None, NOW)


def _past_booking(db, user, haircut, jasur) -> Booking:
    """Wednesday, already over. Inserted directly: the rules refuse the past."""
    start = datetime(2026, 9, 30, 5, 0, tzinfo=UTC)
    booking = Booking(
        customer_id=user.id,
        provider_id=jasur.id,
        service_id=haircut.id,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        status=BookingStatus.COMPLETED,
        price_amount=60_000,
        duration_minutes=30,
    )
    db.add(booking)
    db.flush()
    return booking


def _cancel(client, booking: Booking, **data):
    return client.post(
        f"/me/bookings/{booking.id}/cancel",
        data={"csrf_token": CSRF, **data},
        follow_redirects=False,
    )


# --- The list --------------------------------------------------------------------------


def test_the_list_needs_an_account_and_comes_back_after_login(client):
    response = client.get("/me/bookings", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Fme%2Fbookings"


def test_the_list_shows_your_upcoming_booking_with_its_status_in_words(
    client, db, haircut, jasur, aziza
):
    booking = _book(db, aziza, haircut, jasur)
    _sign_in(client, aziza)

    response = client.get("/me/bookings")

    html = response.text
    assert response.status_code == 200
    assert f'href="/me/bookings/{booking.id}">Fri 2 Oct 2026</a>' in html
    assert "09:00–09:30" in html
    assert "Haircut" in html and "Jasur" in html
    assert f"60{NBSP}000{NBSP}UZS" in html
    assert 'class="status-chip status-chip--pending">Pending</span>' in html
    assert 'href="/me/bookings" aria-current="page">Upcoming</a>' in html


def test_only_your_own_bookings_are_listed(client, db, haircut, jasur, aziza, bob):
    mine = _book(db, aziza, haircut, jasur, NINE)
    theirs = _book(db, bob, haircut, jasur, TEN)
    _sign_in(client, aziza)

    html = client.get("/me/bookings").text

    assert f"/me/bookings/{mine.id}" in html
    assert f"/me/bookings/{theirs.id}" not in html


def test_the_past_tab_holds_finished_bookings_and_upcoming_does_not(
    client, db, haircut, jasur, aziza
):
    upcoming = _book(db, aziza, haircut, jasur)
    past = _past_booking(db, aziza, haircut, jasur)
    _sign_in(client, aziza)

    on_upcoming = client.get("/me/bookings").text
    on_past = client.get("/me/bookings", params={"tab": "past"}).text

    assert f"/me/bookings/{upcoming.id}" in on_upcoming
    assert f"/me/bookings/{past.id}" not in on_upcoming
    assert f"/me/bookings/{past.id}" in on_past
    assert f"/me/bookings/{upcoming.id}" not in on_past
    assert 'status-chip--completed">Completed</span>' in on_past
    assert 'href="/me/bookings?tab=past" aria-current="page">Past</a>' in on_past


def test_a_cancelled_booking_stays_listed_marked_cancelled(client, db, haircut, jasur, aziza):
    booking = _book(db, aziza, haircut, jasur)
    transition(db, aziza, booking.id, BookingStatus.CANCELLED, NOW)
    _sign_in(client, aziza)

    html = client.get("/me/bookings").text

    assert 'status-chip--cancelled">Cancelled</span>' in html


def test_empty_lists_say_what_to_do(client, aziza):
    _sign_in(client, aziza)

    assert "Nothing coming up." in client.get("/me/bookings").text
    assert "No past bookings yet." in client.get("/me/bookings", params={"tab": "past"}).text


def test_an_unknown_tab_is_a_422_page(client, aziza):
    _sign_in(client, aziza)

    response = client.get("/me/bookings", params={"tab": "soon"})

    assert response.status_code == 422
    assert 'class="site-header"' in response.text


def test_a_page_past_the_last_is_a_404_page(client, aziza):
    _sign_in(client, aziza)

    assert client.get("/me/bookings", params={"page": 2}).status_code == 404


def test_the_header_links_to_my_bookings_only_when_signed_in(client, aziza):
    assert 'href="/me/bookings"' not in client.get("/").text

    _sign_in(client, aziza)

    assert 'href="/me/bookings"' in client.get("/").text


# --- One booking -----------------------------------------------------------------------


def test_the_detail_page_shows_the_ticket_history_and_a_cancel_form(
    client, db, haircut, jasur, aziza
):
    booking = _book(db, aziza, haircut, jasur)
    _sign_in(client, aziza)

    response = client.get(f"/me/bookings/{booking.id}")

    html = response.text
    assert response.status_code == 200
    assert "09:00" in html and "–09:30" in html
    assert "Fri 2 Oct 2026" in html
    assert "Asia/Tashkent" in html
    assert "<dd>Jasur</dd>" in html
    assert "Pending</span>" in html
    assert "Waiting for" in html
    assert "Requested by you" in html
    assert f'action="/me/bookings/{booking.id}/cancel"' in html
    assert 'data-confirm="Cancel this booking?"' in html
    assert 'data-confirm-no="No, keep it"' in html
    assert "data-submit-once" in html
    assert f'name="csrf_token" value="{CSRF}"' in html


def test_someone_else_s_booking_is_a_404_page(client, db, haircut, jasur, aziza, bob):
    theirs = _book(db, bob, haircut, jasur)
    _sign_in(client, aziza)

    response = client.get(f"/me/bookings/{theirs.id}")

    assert response.status_code == 404
    assert "Page not found" in response.text
    assert "Bob" not in response.text


def test_a_missing_booking_looks_the_same_as_someone_else_s(client, db, haircut, jasur, aziza, bob):
    theirs = _book(db, bob, haircut, jasur)
    _sign_in(client, aziza)

    other = client.get(f"/me/bookings/{theirs.id}")
    missing = client.get("/me/bookings/99999")

    assert other.status_code == missing.status_code == 404
    assert other.text == missing.text


def test_an_admin_does_not_get_a_customer_page_for_someone_else_s_booking(
    client, db, haircut, jasur, bob, staff
):
    theirs = _book(db, bob, haircut, jasur)
    _sign_in(client, staff)

    assert client.get(f"/me/bookings/{theirs.id}").status_code == 404
    assert _cancel(client, theirs).status_code == 404


# --- Cancel ----------------------------------------------------------------------------


def test_cancelling_a_pending_booking_from_the_form(client, db, haircut, jasur, aziza):
    booking = _book(db, aziza, haircut, jasur)
    _sign_in(client, aziza)

    response = _cancel(client, booking)

    db.refresh(booking)
    events = db.scalars(select(BookingEvent).where(BookingEvent.booking_id == booking.id)).all()
    assert response.status_code == 303
    assert response.headers["location"] == f"/me/bookings/{booking.id}"
    assert f"{FLASH_COOKIE}=cancelled" in response.headers["set-cookie"]
    assert booking.status == BookingStatus.CANCELLED
    assert booking.cancelled_by_id == aziza.id
    assert [e.to_status for e in events] == [BookingStatus.PENDING, BookingStatus.CANCELLED]


def test_after_cancelling_the_page_says_so_and_offers_no_cancel(client, db, haircut, jasur, aziza):
    booking = _book(db, aziza, haircut, jasur)
    _sign_in(client, aziza)
    _cancel(client, booking)

    html = client.get(f"/me/bookings/{booking.id}").text

    assert "Cancelled</span>" in html
    assert "Cancelled by you" in html
    assert "/cancel" not in html
    assert "Can't make it?" not in html


def test_the_time_is_free_again_after_cancelling(client, db, haircut, jasur, aziza, bob):
    booking = _book(db, aziza, haircut, jasur)
    _sign_in(client, aziza)
    _cancel(client, booking)

    assert _book(db, bob, haircut, jasur).id != booking.id  # no 409 SLOT_TAKEN


def test_cancelling_someone_else_s_booking_is_a_404_and_changes_nothing(
    client, db, haircut, jasur, aziza, bob
):
    theirs = _book(db, bob, haircut, jasur)
    _sign_in(client, aziza)

    response = _cancel(client, theirs)

    db.refresh(theirs)
    assert response.status_code == 404
    assert theirs.status == BookingStatus.PENDING


def test_cancelling_without_the_csrf_token_is_refused(client, db, haircut, jasur, aziza):
    booking = _book(db, aziza, haircut, jasur)
    _sign_in(client, aziza)

    response = client.post(f"/me/bookings/{booking.id}/cancel", follow_redirects=False)

    db.refresh(booking)
    assert response.status_code == 403
    assert booking.status == BookingStatus.PENDING


def test_a_confirmed_booking_can_be_cancelled_until_the_cutoff(
    client, db, frozen_clock, haircut, jasur, aziza, staff
):
    booking = _book(db, aziza, haircut, jasur)
    transition(db, staff, booking.id, BookingStatus.CONFIRMED, NOW)
    frozen_clock.advance(NINE - timedelta(hours=2) - NOW)  # exactly the cutoff
    _sign_in(client, aziza, frozen_clock.now())

    page = client.get(f"/me/bookings/{booking.id}").text

    assert "You can cancel online until" in page
    assert 'action="/me/bookings/' in page
    assert _cancel(client, booking).status_code == 303


def test_past_the_cutoff_the_button_is_replaced_by_an_explanation(
    client, db, frozen_clock, haircut, jasur, aziza, staff
):
    booking = _book(db, aziza, haircut, jasur)
    transition(db, staff, booking.id, BookingStatus.CONFIRMED, NOW)
    frozen_clock.advance(NINE - timedelta(hours=2) - NOW + timedelta(minutes=30))
    _sign_in(client, aziza, frozen_clock.now())

    html = client.get(f"/me/bookings/{booking.id}").text

    assert "Confirmed</span>" in html
    assert "Online cancellation closed at" in html
    assert '<span class="mono">07:00</span>' in html
    assert "2 hours before it starts" in html
    assert "/cancel" not in html


def test_pressing_cancel_past_the_cutoff_shows_why_and_changes_nothing(
    client, db, frozen_clock, haircut, jasur, aziza, staff
):
    """The page was open before the cutoff passed; the server still enforces it."""
    booking = _book(db, aziza, haircut, jasur)
    transition(db, staff, booking.id, BookingStatus.CONFIRMED, NOW)
    frozen_clock.advance(NINE - timedelta(hours=1) - NOW)
    _sign_in(client, aziza, frozen_clock.now())

    response = _cancel(client, booking)

    db.refresh(booking)
    assert response.status_code == 409
    assert "too late to cancel this booking online" in response.text
    assert 'role="alert"' in response.text
    assert booking.status == BookingStatus.CONFIRMED


def test_a_booking_that_has_started_says_so(client, db, frozen_clock, haircut, jasur, aziza):
    booking = _book(db, aziza, haircut, jasur)
    frozen_clock.advance(NINE + timedelta(minutes=10) - NOW)
    _sign_in(client, aziza, frozen_clock.now())

    html = client.get(f"/me/bookings/{booking.id}").text

    assert "has already started" in html
    assert "/cancel" not in html


def test_cancelling_twice_shows_the_booking_as_it_is(client, db, haircut, jasur, aziza):
    booking = _book(db, aziza, haircut, jasur)
    _sign_in(client, aziza)
    _cancel(client, booking)

    response = _cancel(client, booking)  # a double submit, or a second tab

    assert response.status_code == 409
    assert "A cancelled booking cannot become cancelled." in response.text
    assert "Cancelled</span>" in response.text
