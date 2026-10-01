"""POST/GET /bookings: create, list, detail, IDOR, auth, naive datetime (P6.3).

Frozen clock: 2026-10-01 07:00 UTC. 2026-10-05 is a Monday; Tashkent is UTC+5,
so 10:00 local is 05:00 UTC. The provider works 09:00-12:00 on Mondays.
"""

from datetime import time, timedelta

import pytest

from app.core.security import create_access_token, hash_password
from app.models import AvailabilityRule, Provider, ProviderService, Service, User, UserRole
from tests.support import add_barber

TEN = "2026-10-05T05:00:00Z"
ELEVEN = "2026-10-05T06:00:00Z"


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


def login_as(db, clock, email, role=UserRole.CUSTOMER) -> dict[str, str]:
    user = User(email=email, password_hash=hash_password("x"), full_name=email, role=role)
    db.add(user)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(user.id, clock.now())}"}


@pytest.fixture
def ali(db, frozen_clock):
    return login_as(db, frozen_clock, "ali@example.com")


@pytest.fixture
def bob(db, frozen_clock):
    return login_as(db, frozen_clock, "bob@example.com")


def payload(setup, start=TEN, **extra):
    service, provider = setup
    return {"service_id": service.id, "provider_id": provider.id, "start_at": start, **extra}


def test_create_returns_201_with_snapshot(client, ali, setup):
    response = client.post("/api/v1/bookings", json=payload(setup, notes="  fade  "), headers=ali)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["start_at"].startswith("2026-10-05T05:00:00")
    assert body["end_at"].startswith("2026-10-05T05:30:00")
    assert body["price_amount"] == 60000
    assert body["duration_minutes"] == 30
    assert body["notes"] == "fade"


def test_offset_start_is_converted_to_the_same_instant(client, ali, setup):
    response = client.post(
        "/api/v1/bookings", json=payload(setup, start="2026-10-05T10:00:00+05:00"), headers=ali
    )
    assert response.status_code == 201
    assert response.json()["start_at"].startswith("2026-10-05T05:00:00")


def test_naive_datetime_is_422(client, ali, setup):
    response = client.post(
        "/api/v1/bookings", json=payload(setup, start="2026-10-05T10:00:00"), headers=ali
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_anonymous_is_401_on_every_endpoint(client, setup):
    assert client.post("/api/v1/bookings", json=payload(setup)).status_code == 401
    assert client.get("/api/v1/bookings").status_code == 401
    assert client.get("/api/v1/bookings/1").status_code == 401


def test_taken_slot_is_409_slot_taken(client, ali, bob, setup):
    client.post("/api/v1/bookings", json=payload(setup), headers=ali)
    response = client.post("/api/v1/bookings", json=payload(setup), headers=bob)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SLOT_TAKEN"


def test_booking_rule_violation_uses_its_code(client, ali, setup):
    response = client.post(
        "/api/v1/bookings", json=payload(setup, start="2026-10-05T05:07:00Z"), headers=ali
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "NOT_ALIGNED"


def test_list_shows_only_my_bookings_with_scope_and_status(client, ali, bob, setup):
    client.post("/api/v1/bookings", json=payload(setup, TEN), headers=ali)
    client.post("/api/v1/bookings", json=payload(setup, ELEVEN), headers=ali)
    client.post("/api/v1/bookings", json=payload(setup, "2026-10-05T07:00:00Z"), headers=bob)

    mine = client.get("/api/v1/bookings", headers=ali).json()
    assert mine["total"] == 2
    # Newest start first when no scope is given.
    assert [b["start_at"][:16] for b in mine["items"]] == ["2026-10-05T06:00", "2026-10-05T05:00"]

    upcoming = client.get("/api/v1/bookings?scope=upcoming", headers=ali).json()
    assert [b["start_at"][:16] for b in upcoming["items"]] == [
        "2026-10-05T05:00",
        "2026-10-05T06:00",
    ]
    assert client.get("/api/v1/bookings?scope=past", headers=ali).json()["total"] == 0
    assert client.get("/api/v1/bookings?status=confirmed", headers=ali).json()["total"] == 0
    assert client.get("/api/v1/bookings?status=pending", headers=ali).json()["total"] == 2


def test_past_scope_lists_finished_bookings(client, ali, setup, frozen_clock):
    created = client.post("/api/v1/bookings", json=payload(setup), headers=ali).json()

    frozen_clock.advance(timedelta(days=5))  # the booking is now over
    # The old token expired meanwhile (12 h), so sign in again as the same user.
    later = {
        "Authorization": f"Bearer {create_access_token(created['customer_id'], frozen_clock.now())}"
    }

    assert client.get("/api/v1/bookings?scope=past", headers=later).json()["total"] == 1
    assert client.get("/api/v1/bookings?scope=upcoming", headers=later).json()["total"] == 0


def test_list_is_paginated(client, ali, setup):
    client.post("/api/v1/bookings", json=payload(setup, TEN), headers=ali)
    client.post("/api/v1/bookings", json=payload(setup, ELEVEN), headers=ali)

    page = client.get("/api/v1/bookings?limit=1&offset=1", headers=ali).json()

    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["items"][0]["start_at"].startswith("2026-10-05T05:00")


def test_detail_of_my_own_booking(client, ali, setup):
    booking_id = client.post("/api/v1/bookings", json=payload(setup), headers=ali).json()["id"]

    response = client.get(f"/api/v1/bookings/{booking_id}", headers=ali)

    assert response.status_code == 200
    assert response.json()["id"] == booking_id


def test_another_customers_booking_is_404_not_403(client, ali, bob, setup):
    booking_id = client.post("/api/v1/bookings", json=payload(setup), headers=ali).json()["id"]

    response = client.get(f"/api/v1/bookings/{booking_id}", headers=bob)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BOOKING_NOT_FOUND"


def test_missing_booking_looks_the_same_as_someone_elses(client, bob):
    response = client.get("/api/v1/bookings/999999", headers=bob)
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "BOOKING_NOT_FOUND"


def test_a_barber_can_read_their_clients_booking_but_lists_only_their_own(
    client, db, frozen_clock, ali, setup
):
    booking_id = client.post("/api/v1/bookings", json=payload(setup), headers=ali).json()["id"]
    barber = add_barber(db, "boss@example.com", provider=setup[1])
    boss = {"Authorization": f"Bearer {create_access_token(barber.id, frozen_clock.now())}"}

    assert client.get(f"/api/v1/bookings/{booking_id}", headers=boss).status_code == 200
    assert client.get("/api/v1/bookings", headers=boss).json()["total"] == 0
