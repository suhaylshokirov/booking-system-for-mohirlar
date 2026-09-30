"""Booking in the browser: the picker, the live grid, confirm, and lost races (P8.4).

Frozen clock: Thursday 2026-10-01 07:00 UTC, 12:00 in Tashkent (UTC+5).
Friday 2026-10-02: Jasur works 09:00-12:00, Bekzod 10:00-11:00 (local).
Default settings: 15-minute grid, 60-minute lead time, 60-day horizon,
2-hour cancellation cutoff.
"""

from datetime import UTC, datetime, time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import create_access_token
from app.models import AvailabilityRule, Booking, BookingStatus, Provider, ProviderService, Service
from app.models.user import User, UserRole
from app.services.booking import create_booking
from app.web.booking import slot_value
from app.web.templating import FLASH_COOKIE

NOW = datetime(2026, 10, 1, 7, tzinfo=UTC)
FRIDAY = "2026-10-02"
NINE = datetime(2026, 10, 2, 4, 0, tzinfo=UTC)  # 09:00 Tashkent
TEN = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)  # 10:00 Tashkent
CSRF = "test-csrf-token"


def _provider(db: Session, service: Service, name: str, start: int, end: int) -> Provider:
    provider = Provider(name=name)
    db.add(provider)
    db.flush()
    db.add(ProviderService(provider_id=provider.id, service_id=service.id))
    db.add(
        AvailabilityRule(
            provider_id=provider.id, weekday=4, start_time=time(start), end_time=time(end)
        )
    )
    db.flush()
    return provider


def _user(db: Session, email: str) -> User:
    user = User(email=email, password_hash="x", full_name="Aziza Karimova", role=UserRole.CUSTOMER)
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
    return _provider(db, haircut, "Jasur", 9, 12)


@pytest.fixture
def bekzod(db, haircut) -> Provider:
    return _provider(db, haircut, "Bekzod", 10, 11)


@pytest.fixture
def aziza(db) -> User:
    return _user(db, "aziza@example.com")


def _sign_in(client, user: User) -> None:
    """Cookies as the browser holds them after logging in."""
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, NOW))
    client.cookies.set(CSRF_COOKIE, CSRF)


def _book(client, service: Service, provider: Provider, start: datetime, **extra):
    data = {
        "slot": slot_value(provider.id, start),
        "provider": "any",
        "csrf_token": CSRF,
        **extra,
    }
    return client.post(f"/book/{service.id}", data=data, follow_redirects=False)


# --- The picker ---------------------------------------------------------------------


def test_picker_is_a_full_page_with_everyone_s_free_times(client, haircut, jasur, bekzod):
    response = client.get(f"/book/{haircut.id}", params={"date": FRIDAY})

    html = response.text
    assert response.status_code == 200
    assert "<html" in html and 'class="site-header"' in html
    assert 'id="person-any" name="provider" value="any" checked' in html
    assert "Fri 2 Oct 2026" in html
    assert f'value="{slot_value(jasur.id, NINE)}"' in html  # Jasur from 09:00
    assert f'value="{slot_value(bekzod.id, NINE)}"' not in html  # Bekzod starts at 10
    assert f'value="{slot_value(bekzod.id, TEN)}"' in html
    assert "<span>09:00</span>" in html
    assert 'aria-current="step"' in html
    assert response.headers["vary"] == "X-Requested-With"


def test_live_request_gets_only_the_slot_grid(client, haircut, jasur):
    response = client.get(
        f"/book/{haircut.id}",
        params={"date": FRIDAY, "provider": str(jasur.id)},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )

    html = response.text
    assert response.status_code == 200
    assert "<html" not in html
    assert 'class="site-header"' not in html
    assert 'class="day-title"' in html
    assert f'value="{slot_value(jasur.id, NINE)}"' in html
    assert '<input type="hidden" name="provider" value="' + str(jasur.id) + '">' in html


def test_filtering_by_person_shows_only_them(client, haircut, jasur, bekzod):
    html = client.get(
        f"/book/{haircut.id}", params={"date": FRIDAY, "provider": str(bekzod.id)}
    ).text

    assert f'id="person-{bekzod.id}" name="provider" value="{bekzod.id}" checked' in html
    assert f'value="{slot_value(bekzod.id, TEN)}"' in html
    assert f"|{NINE.isoformat()}" not in html  # nobody else's tiles


def test_a_day_without_free_time_points_to_the_next_day(client, haircut, jasur):
    html = client.get(f"/book/{haircut.id}").text  # defaults to today, Thursday

    assert "No free times on Thu 1 Oct 2026." in html
    assert f'date={FRIDAY}">Try Fri 2 Oct 2026</a>' in html
    assert 'rel="prev"' not in html  # nothing before today


def test_a_day_past_the_horizon_says_which_days_can_be_booked(client, haircut, jasur):
    response = client.get(f"/book/{haircut.id}", params={"date": "2027-01-01"})

    assert response.status_code == 422
    assert "Pick a date from 2026-10-01 to 2026-11-30." in response.text
    assert 'class="site-header"' in response.text  # a page, not an error screen


def test_a_retired_service_cannot_be_booked(client, db, haircut, jasur):
    haircut.is_active = False
    db.flush()

    assert client.get(f"/book/{haircut.id}").status_code == 404


def test_a_malformed_person_filter_is_a_422_page(client, haircut):
    assert client.get(f"/book/{haircut.id}", params={"provider": "jasur"}).status_code == 422


# --- Confirm -------------------------------------------------------------------------


def test_confirm_needs_an_account_and_comes_back_after_login(client, haircut, jasur):
    slot = slot_value(jasur.id, NINE)

    response = client.get(
        f"/book/{haircut.id}/confirm", params={"slot": slot}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?next=%2Fbook%2F")


def test_confirm_shows_the_ticket_and_the_cancellation_policy(client, haircut, jasur, aziza):
    _sign_in(client, aziza)

    response = client.get(
        f"/book/{haircut.id}/confirm", params={"slot": slot_value(jasur.id, NINE)}
    )

    html = response.text
    assert response.status_code == 200
    assert "09:00" in html and "–09:30" in html
    assert "Fri 2 Oct 2026" in html
    assert "Asia/Tashkent" in html
    assert "<dd>Jasur</dd>" in html
    assert "60 000 UZS" in html
    assert '<span class="mono">07:00</span> on Fri 2 Oct 2026' in html  # 2 h before 09:00
    assert 'class="btn btn--commit"' in html
    assert f'name="csrf_token" value="{CSRF}"' in html


def test_confirm_without_a_chosen_time_returns_to_the_picker(client, haircut, jasur, aziza):
    _sign_in(client, aziza)

    response = client.get(f"/book/{haircut.id}/confirm")

    assert response.status_code == 422
    assert "Pick a time first." in response.text


def test_confirm_for_a_time_taken_meanwhile_returns_to_the_picker(
    client, db, haircut, jasur, aziza
):
    create_booking(db, _user(db, "bob@example.com"), haircut.id, jasur.id, NINE, None, NOW)
    _sign_in(client, aziza)

    response = client.get(
        f"/book/{haircut.id}/confirm", params={"slot": slot_value(jasur.id, NINE)}
    )

    assert response.status_code == 409
    assert "That time is no longer free — pick another." in response.text
    assert "Fri 2 Oct 2026" in response.text  # back on the same day


# --- Booking --------------------------------------------------------------------------


def test_booking_creates_a_pending_booking_and_goes_to_it(client, db, haircut, jasur, aziza):
    _sign_in(client, aziza)

    response = _book(client, haircut, jasur, NINE, notes="Short on the sides")

    booking = db.scalar(select(Booking).where(Booking.customer_id == aziza.id))
    assert response.status_code == 303
    assert response.headers["location"] == f"/me/bookings/{booking.id}"
    assert f"{FLASH_COOKIE}=booked" in response.headers["set-cookie"]
    assert booking.status == BookingStatus.PENDING
    assert booking.start_at == NINE
    assert booking.notes == "Short on the sides"


def test_a_slot_taken_between_viewing_and_booking_shows_the_grid_again(
    client, db, haircut, jasur, aziza
):
    create_booking(db, _user(db, "bob@example.com"), haircut.id, jasur.id, NINE, None, NOW)
    _sign_in(client, aziza)

    response = _book(client, haircut, jasur, NINE)

    html = response.text
    assert response.status_code == 409
    assert "That time was just taken — pick another." in html
    assert f'value="{slot_value(jasur.id, NINE)}"' not in html  # the taken tile is gone
    assert "<span>09:30</span>" in html  # the rest of the day is offered again
    assert db.scalar(select(Booking).where(Booking.customer_id == aziza.id)) is None


def test_booking_over_your_own_other_booking_explains_why(
    client, db, haircut, jasur, bekzod, aziza
):
    create_booking(db, aziza, haircut.id, bekzod.id, TEN, None, NOW)
    _sign_in(client, aziza)

    response = _book(client, haircut, jasur, TEN)

    assert response.status_code == 409
    assert "You already have a booking that overlaps this time." in response.text


def test_booking_a_time_inside_the_lead_time_explains_why(client, db, haircut, jasur, aziza):
    # Thursday hours so a slot today exists on the grid but is too soon.
    db.add(
        AvailabilityRule(provider_id=jasur.id, weekday=3, start_time=time(12), end_time=time(18))
    )
    db.flush()
    _sign_in(client, aziza)

    response = _book(client, haircut, jasur, datetime(2026, 10, 1, 7, 30, tzinfo=UTC))  # 12:30

    assert response.status_code == 422
    assert 'class="notice notice--error"' in response.text


def test_booking_without_a_time_asks_for_one(client, haircut, jasur, aziza):
    _sign_in(client, aziza)

    response = client.post(f"/book/{haircut.id}", data={"csrf_token": CSRF}, follow_redirects=False)

    assert response.status_code == 422
    assert "Pick a time first." in response.text


def test_an_overlong_note_is_sent_back_to_the_confirm_step(client, haircut, jasur, aziza):
    _sign_in(client, aziza)

    response = _book(client, haircut, jasur, NINE, notes="x" * 501)

    assert response.status_code == 422
    assert "Keep the note under 500 characters." in response.text
    assert "Confirm your booking" in response.text


def test_booking_without_the_csrf_token_is_refused(client, db, haircut, jasur, aziza):
    _sign_in(client, aziza)

    response = client.post(
        f"/book/{haircut.id}",
        data={"slot": slot_value(jasur.id, NINE)},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert db.scalar(select(Booking).where(Booking.customer_id == aziza.id)) is None


def test_confirm_form_submits_once(client, haircut, jasur, aziza):
    """UI half of double submit; the server half is the exclusion constraint."""
    _sign_in(client, aziza)

    html = client.get(
        f"/book/{haircut.id}/confirm", params={"slot": slot_value(jasur.id, NINE)}
    ).text

    assert 'class="form booking-confirm" method="post"' in html
    assert "data-submit-once" in html
