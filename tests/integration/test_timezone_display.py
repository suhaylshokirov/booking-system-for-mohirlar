"""Times are never ambiguous: UTC and local in the API, the zone in the pages (P10.3).

Frozen clock: 2026-10-01 07:00 UTC. The provider works Mondays 09:00-12:00 on
the business's clock. Tashkent is UTC+5 all year. Berlin is UTC+2 until the
clocks go back on 2026-10-25, then UTC+1, so Monday 2026-10-05 09:00 is 07:00
UTC and Monday 2026-11-02 09:00 is 08:00 UTC.
"""

from datetime import time

import pytest

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.core.security import create_access_token, hash_password
from app.models import AvailabilityRule, Provider, ProviderService, Service, User, UserRole
from app.services.business_settings import get_business_settings

BOOKINGS = "/api/v1/bookings"


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


@pytest.fixture
def berlin(db):
    get_business_settings(db).timezone = "Europe/Berlin"
    db.flush()


def make_user(db, email, role=UserRole.CUSTOMER) -> User:
    user = User(email=email, password_hash=hash_password("x"), full_name=email, role=role)
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def ali(db):
    return make_user(db, "ali@example.com")


def bearer(user, clock):
    return {"Authorization": f"Bearer {create_access_token(user.id, clock.now())}"}


def book(client, setup, ali, clock, start_at) -> dict:
    service, provider = setup
    response = client.post(
        BOOKINGS,
        json={"service_id": service.id, "provider_id": provider.id, "start_at": start_at},
        headers=bearer(ali, clock),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_booking_carries_utc_and_local_time_and_the_zone(client, setup, ali, frozen_clock):
    body = book(client, setup, ali, frozen_clock, "2026-10-05T05:00:00Z")

    assert body["start_at"].startswith("2026-10-05T05:00:00")
    assert body["local_start"] == "2026-10-05T10:00:00+05:00"
    assert body["local_end"] == "2026-10-05T10:30:00+05:00"
    assert body["timezone"] == "Asia/Tashkent"


def test_a_berlin_business_shows_berlin_summer_time(client, setup, berlin, ali, frozen_clock):
    body = book(client, setup, ali, frozen_clock, "2026-10-05T07:00:00Z")

    assert body["start_at"].startswith("2026-10-05T07:00:00")
    assert body["local_start"] == "2026-10-05T09:00:00+02:00"
    assert body["local_end"] == "2026-10-05T09:30:00+02:00"
    assert body["timezone"] == "Europe/Berlin"


def test_after_the_clocks_change_the_same_wall_time_has_a_different_offset(
    client, setup, berlin, ali, frozen_clock
):
    body = book(client, setup, ali, frozen_clock, "2026-11-02T08:00:00Z")

    assert body["local_start"] == "2026-11-02T09:00:00+01:00"


def test_every_booking_endpoint_includes_the_local_fields(
    client, setup, berlin, ali, db, frozen_clock
):
    created = book(client, setup, ali, frozen_clock, "2026-10-05T07:00:00Z")
    headers = bearer(ali, frozen_clock)
    staff = bearer(make_user(db, "staff@example.com", UserRole.ADMIN), frozen_clock)

    read = client.get(f"{BOOKINGS}/{created['id']}", headers=headers).json()
    listed = client.get(BOOKINGS, headers=headers).json()["items"][0]
    everyone = client.get(f"{BOOKINGS}/all", headers=staff).json()["items"][0]
    confirmed = client.post(f"{BOOKINGS}/{created['id']}/confirm", headers=staff).json()
    cancelled = client.post(f"{BOOKINGS}/{created['id']}/cancel", headers=headers).json()

    for body in (read, listed, everyone, confirmed, cancelled):
        assert body["local_start"] == "2026-10-05T09:00:00+02:00"
        assert body["timezone"] == "Europe/Berlin"
    assert "stale_pending" in everyone


def test_slots_carry_local_times_in_the_business_zone(client, setup, berlin):
    service, _ = setup

    body = client.get(
        "/api/v1/slots", params={"service_id": service.id, "date": "2026-10-05"}
    ).json()

    first = body["providers"][0]["slots"][0]
    assert first["start_at"].startswith("2026-10-05T07:00:00")
    assert first["local_start"] == "2026-10-05T09:00:00+02:00"
    assert first["local_end"] == "2026-10-05T09:30:00+02:00"
    assert body["timezone"] == "Europe/Berlin"


def _sign_in(client, user, clock):
    client.cookies.set(ACCESS_COOKIE, create_access_token(user.id, clock.now()))
    client.cookies.set(CSRF_COOKIE, "test-csrf-token")


def test_pages_name_the_zone_and_offset_for_a_berlin_business(
    client, setup, berlin, ali, frozen_clock
):
    summer = book(client, setup, ali, frozen_clock, "2026-10-05T07:00:00Z")
    winter = book(client, setup, ali, frozen_clock, "2026-11-02T08:00:00Z")
    _sign_in(client, ali, frozen_clock)

    page = client.get(f"/me/bookings/{summer['id']}").text
    assert "09:00" in page and "Europe/Berlin · UTC+2" in page
    assert "Asia/Tashkent" not in page

    page = client.get(f"/me/bookings/{winter['id']}").text
    assert "09:00" in page and "Europe/Berlin · UTC+1" in page

    listing = client.get("/me/bookings").text
    assert '<span class="zone">UTC+2</span>' in listing
    assert '<span class="zone">UTC+1</span>' in listing


def test_the_slot_picker_says_which_clock_the_day_is_on(client, setup, berlin, frozen_clock):
    service, _ = setup

    page = client.get(f"/book/{service.id}", params={"date": "2026-10-26"}).text

    # 2026-10-26 is after the clocks went back, so the picker says UTC+1, not UTC+2.
    assert "Europe/Berlin</span>, UTC+1." in page


def test_customer_pages_carry_the_hidden_note_for_a_device_on_another_clock(
    client, setup, berlin, ali, frozen_clock
):
    booking = book(client, setup, ali, frozen_clock, "2026-10-05T07:00:00Z")
    _sign_in(client, ali, frozen_clock)
    service, _ = setup

    for path in ("/me/bookings", f"/me/bookings/{booking['id']}", f"/book/{service.id}"):
        page = client.get(path).text
        assert 'data-business-timezone="Europe/Berlin" hidden' in page, path
