"""GET /bookings/{id}/ics and /me/bookings/{id}/ics (P10.1).

Frozen clock: 2026-10-01 07:00 UTC. Monday 2026-10-05, 10:00 Tashkent = 05:00 UTC.
"""

from datetime import time

import pytest

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import create_access_token, hash_password
from app.models import AvailabilityRule, Provider, ProviderService, Service, User, UserRole
from tests.support import add_barber

TEN = "2026-10-05T05:00:00Z"
NOTE = r"Short, on the sides; no \ clippers"


@pytest.fixture
def setup(db):
    service = Service(name="Haircut", duration_minutes=30, price=60000)
    provider = Provider(name="Jasur")
    db.add_all([service, provider])
    db.flush()
    db.add(ProviderService(provider_id=provider.id, service_id=service.id))
    db.add(
        AvailabilityRule(provider_id=provider.id, weekday=0, start_time=time(9), end_time=time(12))
    )
    db.flush()
    return service, provider


def make_user(db, email, role=UserRole.CUSTOMER) -> User:
    user = User(email=email, password_hash=hash_password("x"), full_name=email, role=role)
    db.add(user)
    db.flush()
    return user


def bearer(user, clock) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, clock.now())}"}


@pytest.fixture
def ali(db):
    return make_user(db, "ali@example.com")


@pytest.fixture
def booking_id(client, setup, ali, frozen_clock) -> int:
    service, provider = setup
    response = client.post(
        "/api/v1/bookings",
        json={
            "service_id": service.id,
            "provider_id": provider.id,
            "start_at": TEN,
            "notes": NOTE,
        },
        headers=bearer(ali, frozen_clock),
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_api_returns_a_calendar_file(client, ali, booking_id, frozen_clock):
    response = client.get(f"/api/v1/bookings/{booking_id}/ics", headers=bearer(ali, frozen_clock))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert f'filename="booking-{booking_id}.ics"' in response.headers["content-disposition"]
    body = response.text
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    for field in (
        f"UID:booking-{booking_id}@navbat",
        "DTSTAMP:",
        "DTSTART:20261005T050000Z",
        "DTEND:20261005T053000Z",
        "SUMMARY:Haircut with Jasur",
        "LOCATION:",
        "STATUS:TENTATIVE",
    ):
        assert field in body


def test_notes_with_special_characters_are_escaped(client, ali, booking_id, frozen_clock):
    body = client.get(f"/api/v1/bookings/{booking_id}/ics", headers=bearer(ali, frozen_clock)).text

    unfolded = body.replace("\r\n ", "")
    assert r"Note: Short\, on the sides\; no \\ clippers" in unfolded


def test_a_cancelled_booking_downloads_as_cancelled(client, ali, booking_id, frozen_clock):
    headers = bearer(ali, frozen_clock)
    assert client.post(f"/api/v1/bookings/{booking_id}/cancel", headers=headers).status_code == 200

    body = client.get(f"/api/v1/bookings/{booking_id}/ics", headers=headers).text

    assert "STATUS:CANCELLED" in body


def test_someone_elses_booking_is_404(client, db, booking_id, frozen_clock):
    bob = make_user(db, "bob@example.com")

    response = client.get(f"/api/v1/bookings/{booking_id}/ics", headers=bearer(bob, frozen_clock))

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BOOKING_NOT_FOUND"


def test_the_barber_can_download_their_clients_booking(client, db, setup, booking_id, frozen_clock):
    staff = add_barber(db, "staff@example.com", provider=setup[1])

    response = client.get(f"/api/v1/bookings/{booking_id}/ics", headers=bearer(staff, frozen_clock))

    assert response.status_code == 200


def test_it_needs_a_login(client, booking_id):
    assert client.get(f"/api/v1/bookings/{booking_id}/ics").status_code == 401


def _sign_in(client, user, clock):
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, clock.now()))
    client.cookies.set(CSRF_COOKIE, "test-csrf-token")


def test_the_booking_page_links_to_the_file_and_it_downloads(client, ali, booking_id, frozen_clock):
    _sign_in(client, ali, frozen_clock)

    page = client.get(f"/me/bookings/{booking_id}")
    assert f'href="/me/bookings/{booking_id}/ics"' in page.text

    response = client.get(f"/me/bookings/{booking_id}/ics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VEVENT" in response.text


def test_the_page_has_no_calendar_link_once_cancelled(client, ali, booking_id, frozen_clock):
    _sign_in(client, ali, frozen_clock)
    client.post(f"/me/bookings/{booking_id}/cancel", data={"csrf_token": "test-csrf-token"})

    assert "/ics" not in client.get(f"/me/bookings/{booking_id}").text


def test_the_web_file_for_someone_elses_booking_is_404(client, db, booking_id, frozen_clock):
    _sign_in(client, make_user(db, "bob@example.com"), frozen_clock)

    assert client.get(f"/me/bookings/{booking_id}/ics").status_code == 404
