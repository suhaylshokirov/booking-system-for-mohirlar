"""GET/PATCH /settings against a real PostgreSQL (P3.1)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.business_settings import BusinessSettings
from app.models.service import Service

SETTINGS = "/api/v1/settings"


def _service(db: Session, duration: int, *, active: bool = True, name: str = "Haircut") -> Service:
    service = Service(name=name, duration_minutes=duration, price=50000, is_active=active)
    db.add(service)
    db.flush()
    return service


# --- read ------------------------------------------------------------------


def test_anyone_can_read_settings_and_a_missing_row_is_created_with_defaults(client, db):
    assert db.scalar(select(func.count()).select_from(BusinessSettings)) == 0

    response = client.get(SETTINGS)  # anonymous

    assert response.status_code == 200
    body = response.json()
    assert body["timezone"] == "Asia/Tashkent"
    assert body["currency"] == "UZS"
    assert body["slot_granularity_minutes"] == 15
    assert body["min_lead_time_minutes"] == 60
    assert body["max_booking_horizon_days"] == 60
    assert body["cancellation_cutoff_hours"] == 2
    assert "id" not in body
    assert db.scalar(select(func.count()).select_from(BusinessSettings)) == 1


def test_reading_twice_does_not_create_a_second_row(client, db):
    client.get(SETTINGS)
    client.get(SETTINGS)
    assert db.scalar(select(func.count()).select_from(BusinessSettings)) == 1


def test_read_returns_seeded_values(client, db):
    db.add(BusinessSettings(id=1, name="Barbershop Navbat", timezone="Asia/Samarkand"))
    db.flush()
    body = client.get(SETTINGS).json()
    assert body["name"] == "Barbershop Navbat"
    assert body["timezone"] == "Asia/Samarkand"


# --- update ----------------------------------------------------------------


def test_admin_can_update_some_fields_and_the_rest_are_kept(client, admin):
    response = client.patch(
        SETTINGS,
        json={"name": "  Fresh Cuts  ", "max_booking_horizon_days": 30, "timezone": "Europe/Paris"},
        headers=admin,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Fresh Cuts"
    assert body["max_booking_horizon_days"] == 30
    assert body["timezone"] == "Europe/Paris"
    assert body["slot_granularity_minutes"] == 15  # untouched
    # The change is really stored, not just echoed back.
    assert client.get(SETTINGS).json()["max_booking_horizon_days"] == 30


def test_customer_cannot_update_settings(client, customer):
    response = client.patch(SETTINGS, json={"currency": "USD"}, headers=customer)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    assert client.get(SETTINGS).json()["currency"] == "UZS"


def test_anonymous_cannot_update_settings(client):
    response = client.patch(SETTINGS, json={"currency": "USD"})
    assert response.status_code == 401


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize("name", ["Mars/Olympus", "Asia", "../etc/passwd", "Tashkent"])
def test_invalid_timezone_is_422(client, admin, name):
    response = client.patch(SETTINGS, json={"timezone": name}, headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TIMEZONE"
    assert client.get(SETTINGS).json()["timezone"] == "Asia/Tashkent"


@pytest.mark.parametrize(
    "body",
    [
        {"slot_granularity_minutes": 7},
        {"slot_granularity_minutes": 0},
        {"min_lead_time_minutes": -1},
        {"max_booking_horizon_days": 0},
        {"max_booking_horizon_days": 366},
        {"cancellation_cutoff_hours": -1},
        {"currency": "uzs"},
        {"currency": "SUMS"},
        {"name": "   "},
        {"name": "x" * 101},
        {"timezone": None},
        {},
    ],
)
def test_out_of_range_values_are_422(client, admin, body):
    response = client.patch(SETTINGS, json=body, headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.parametrize(
    "body",
    [
        {"slot_granularity_minutes": 5},
        {"slot_granularity_minutes": 60},
        {"min_lead_time_minutes": 0},
        {"max_booking_horizon_days": 1},
        {"max_booking_horizon_days": 365},
        {"cancellation_cutoff_hours": 0},
    ],
)
def test_boundary_values_are_accepted(client, admin, body):
    assert client.patch(SETTINGS, json=body, headers=admin).status_code == 200


# --- granularity vs. service durations -------------------------------------


def test_granularity_change_is_refused_when_an_active_service_does_not_fit(client, admin, db):
    _service(db, 45, name="Haircut")  # fits 15, not 30
    _service(db, 60, name="Beard trim")  # fits both

    response = client.patch(SETTINGS, json={"slot_granularity_minutes": 30}, headers=admin)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "GRANULARITY_CONFLICT"
    assert [s["name"] for s in error["details"]["services"]] == ["Haircut"]
    assert error["details"]["services"][0]["duration_minutes"] == 45
    assert client.get(SETTINGS).json()["slot_granularity_minutes"] == 15  # unchanged


def test_granularity_change_is_allowed_when_every_active_service_fits(client, admin, db):
    _service(db, 30)
    _service(db, 90, name="Full grooming")
    response = client.patch(SETTINGS, json={"slot_granularity_minutes": 30}, headers=admin)
    assert response.status_code == 200
    assert response.json()["slot_granularity_minutes"] == 30


def test_inactive_services_do_not_block_a_granularity_change(client, admin, db):
    _service(db, 45, active=False)
    response = client.patch(SETTINGS, json={"slot_granularity_minutes": 30}, headers=admin)
    assert response.status_code == 200


def test_a_refused_change_applies_none_of_its_fields(client, admin, db):
    _service(db, 45)
    response = client.patch(
        SETTINGS, json={"slot_granularity_minutes": 30, "currency": "USD"}, headers=admin
    )
    assert response.status_code == 409
    assert client.get(SETTINGS).json()["currency"] == "UZS"
