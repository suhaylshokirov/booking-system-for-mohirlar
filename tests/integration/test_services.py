"""/services against a real PostgreSQL (P3.2)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, BookingStatus, Provider, Service, User
from app.models.business_settings import BusinessSettings

SERVICES = "/api/v1/services"
VALID = {"name": "Haircut", "description": "Wash and cut.", "duration_minutes": 30, "price": 60000}


def _service(db: Session, name="Haircut", minutes=30, price=60000, active=True) -> Service:
    service = Service(name=name, duration_minutes=minutes, price=price, is_active=active)
    db.add(service)
    db.flush()
    return service


def _set_granularity(db: Session, minutes: int) -> None:
    db.add(BusinessSettings(id=1, name="Test", slot_granularity_minutes=minutes))
    db.flush()


# --- create ----------------------------------------------------------------


def test_admin_creates_a_service(client, admin, db):
    response = client.post(SERVICES, json=VALID, headers=admin)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Haircut"
    assert body["description"] == "Wash and cut."
    assert body["duration_minutes"] == 30
    assert body["price"] == 60000
    assert body["is_active"] is True
    assert db.get(Service, body["id"]).name == "Haircut"


def test_create_trims_the_name_and_turns_a_blank_description_into_none(client, admin):
    response = client.post(
        SERVICES, json={**VALID, "name": "  Beard trim  ", "description": "   "}, headers=admin
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Beard trim"
    assert response.json()["description"] is None


def test_description_is_optional_and_a_free_service_is_allowed(client, admin):
    body = {"name": "Consultation", "duration_minutes": 15, "price": 0}
    response = client.post(SERVICES, json=body, headers=admin)
    assert response.status_code == 201
    assert response.json()["price"] == 0


def test_customer_and_anonymous_cannot_create(client, customer):
    assert client.post(SERVICES, json=VALID, headers=customer).status_code == 403
    assert client.post(SERVICES, json=VALID).status_code == 401


@pytest.mark.parametrize(
    "change",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "x" * 101},
        {"description": "x" * 1001},
        {"duration_minutes": 0},
        {"duration_minutes": -30},
        {"duration_minutes": 481},
        {"duration_minutes": 22.5},
        {"duration_minutes": "30"},
        {"price": -1},
        {"price": 10.5},
        {"price": "60000"},
        {"price": 2_147_483_648},
        {"price": True},
    ],
)
def test_invalid_input_is_a_validation_error(client, admin, db, change):
    response = client.post(SERVICES, json={**VALID, **change}, headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert db.scalar(select(Service)) is None


@pytest.mark.parametrize("missing", ["name", "duration_minutes", "price"])
def test_required_fields_are_required(client, admin, missing):
    body = {k: v for k, v in VALID.items() if k != missing}
    assert client.post(SERVICES, json=body, headers=admin).status_code == 422


def test_boundary_values_are_accepted(client, admin):
    body = {"name": "x" * 100, "description": "y" * 1000, "duration_minutes": 480, "price": 0}
    assert client.post(SERVICES, json=body, headers=admin).status_code == 201


def test_duration_must_fit_the_slot_granularity(client, admin, db):
    _set_granularity(db, 30)

    refused = client.post(SERVICES, json={**VALID, "duration_minutes": 45}, headers=admin)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "DURATION_NOT_ALIGNED"
    assert refused.json()["error"]["details"]["slot_granularity_minutes"] == 30
    assert db.scalar(select(Service)) is None

    assert (
        client.post(SERVICES, json={**VALID, "duration_minutes": 60}, headers=admin).status_code
        == 201
    )


# --- list ------------------------------------------------------------------


def test_public_list_shows_active_services_only_in_a_page_envelope(client, db):
    _service(db, "Shave")
    _service(db, "Beard trim", active=False)
    _service(db, "Haircut")

    response = client.get(SERVICES)  # anonymous

    assert response.status_code == 200
    body = response.json()
    assert [s["name"] for s in body["items"]] == ["Haircut", "Shave"]  # alphabetical
    assert (body["total"], body["limit"], body["offset"]) == (2, 20, 0)


def test_list_is_paginated(client, db):
    for n in range(5):
        _service(db, f"Service {n}")

    page = client.get(SERVICES, params={"limit": 2, "offset": 2}).json()

    assert [s["name"] for s in page["items"]] == ["Service 2", "Service 3"]
    assert (page["total"], page["limit"], page["offset"]) == (5, 2, 2)
    assert client.get(SERVICES, params={"offset": 10}).json()["items"] == []


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"limit": -1}, {"offset": -1}])
def test_out_of_range_paging_is_422(client, params):
    response = client.get(SERVICES, params=params)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_the_page_size_is_capped_at_100(client, db):
    assert client.get(SERVICES, params={"limit": 100}).status_code == 200


def test_admin_can_list_inactive_services_too(client, admin, db):
    _service(db, "Haircut")
    _service(db, "Old special", active=False)

    body = client.get(SERVICES, params={"include_inactive": "true"}, headers=admin).json()

    assert [s["name"] for s in body["items"]] == ["Haircut", "Old special"]
    assert body["total"] == 2


def test_asking_for_inactive_services_without_being_admin_is_refused(client, customer, db):
    _service(db, active=False)
    assert client.get(SERVICES, params={"include_inactive": "true"}).status_code == 401
    refused = client.get(SERVICES, params={"include_inactive": "true"}, headers=customer)
    assert refused.status_code == 403
    assert refused.json()["error"]["code"] == "FORBIDDEN"


# --- read one --------------------------------------------------------------


def test_anyone_can_read_an_active_service(client, db):
    service = _service(db)
    response = client.get(f"{SERVICES}/{service.id}")
    assert response.status_code == 200
    assert response.json()["id"] == service.id


def test_an_inactive_service_is_404_for_the_public_and_customers_but_not_admins(
    client, admin, customer, db
):
    service = _service(db, active=False)
    url = f"{SERVICES}/{service.id}"

    assert client.get(url).status_code == 404
    assert client.get(url, headers=customer).status_code == 404
    assert client.get(url, headers=admin).status_code == 200


def test_unknown_service_is_404_in_the_error_envelope(client):
    response = client.get(f"{SERVICES}/999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- update ----------------------------------------------------------------


def test_admin_updates_only_the_fields_sent(client, admin, db):
    service = _service(db, minutes=30, price=60000)

    response = client.patch(f"{SERVICES}/{service.id}", json={"price": 70000}, headers=admin)

    assert response.status_code == 200
    assert response.json()["price"] == 70000
    assert response.json()["duration_minutes"] == 30
    assert response.json()["name"] == "Haircut"


def test_description_can_be_cleared_with_null_but_other_fields_cannot(client, admin, db):
    service = _service(db)
    service.description = "Old text"
    db.flush()
    url = f"{SERVICES}/{service.id}"

    assert (
        client.patch(url, json={"description": None}, headers=admin).json()["description"] is None
    )
    assert client.patch(url, json={"price": None}, headers=admin).status_code == 422
    assert client.patch(url, json={}, headers=admin).status_code == 422


def test_update_validates_like_create(client, admin, db):
    service = _service(db)
    url = f"{SERVICES}/{service.id}"
    assert client.patch(url, json={"price": -5}, headers=admin).status_code == 422
    assert client.patch(url, json={"duration_minutes": 0}, headers=admin).status_code == 422
    assert client.patch(url, json={"name": " "}, headers=admin).status_code == 422


def test_update_keeps_the_duration_on_the_slot_grid(client, admin, db):
    _set_granularity(db, 30)
    service = _service(db, minutes=30)

    refused = client.patch(f"{SERVICES}/{service.id}", json={"duration_minutes": 45}, headers=admin)

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "DURATION_NOT_ALIGNED"
    assert db.get(Service, service.id).duration_minutes == 30


def test_update_unknown_service_is_404(client, admin):
    assert client.patch(f"{SERVICES}/999999", json={"price": 1}, headers=admin).status_code == 404


def test_customer_and_anonymous_cannot_update(client, customer, db):
    service = _service(db)
    url = f"{SERVICES}/{service.id}"
    assert client.patch(url, json={"price": 1}, headers=customer).status_code == 403
    assert client.patch(url, json={"price": 1}).status_code == 401
    assert db.get(Service, service.id).price == 60000


# --- deactivate / activate -------------------------------------------------


def test_deactivating_hides_the_service_and_activating_shows_it_again(client, admin, db):
    service = _service(db)
    url = f"{SERVICES}/{service.id}"

    deactivated = client.post(f"{url}/deactivate", headers=admin)
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert client.get(url).status_code == 404
    assert client.get(SERVICES).json()["items"] == []

    activated = client.post(f"{url}/activate", headers=admin)
    assert activated.json()["is_active"] is True
    assert client.get(url).status_code == 200


def test_repeating_deactivate_or_activate_is_harmless(client, admin, db):
    service = _service(db)
    url = f"{SERVICES}/{service.id}"
    assert client.post(f"{url}/activate", headers=admin).status_code == 200
    assert client.post(f"{url}/deactivate", headers=admin).status_code == 200
    assert client.post(f"{url}/deactivate", headers=admin).status_code == 200


def test_activation_and_deactivation_are_admin_only_and_404_for_unknown(
    client, admin, customer, db
):
    service = _service(db)
    assert client.post(f"{SERVICES}/{service.id}/deactivate", headers=customer).status_code == 403
    assert client.post(f"{SERVICES}/{service.id}/deactivate").status_code == 401
    assert client.post(f"{SERVICES}/999999/activate", headers=admin).status_code == 404


def test_activating_a_service_that_no_longer_fits_the_grid_is_refused(client, admin, db):
    service = _service(db, minutes=45, active=False)
    _set_granularity(db, 30)  # changed while the service was inactive

    response = client.post(f"{SERVICES}/{service.id}/activate", headers=admin)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DURATION_NOT_ALIGNED"
    assert db.get(Service, service.id).is_active is False


def test_deactivating_or_editing_a_service_keeps_its_bookings_untouched(client, admin, db):
    service = _service(db, minutes=30, price=60000)
    customer_user = User(email="ali@example.uz", password_hash="x", full_name="Ali")
    provider = Provider(name="Jasur")
    db.add_all([customer_user, provider])
    db.flush()
    start = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    booking = Booking(
        customer_id=customer_user.id,
        provider_id=provider.id,
        service_id=service.id,
        start_at=start,
        end_at=start.replace(minute=30),
        status=BookingStatus.CONFIRMED,
        price_amount=60000,
        duration_minutes=30,
    )
    db.add(booking)
    db.flush()
    url = f"{SERVICES}/{service.id}"

    assert (
        client.patch(url, json={"price": 99000, "duration_minutes": 60}, headers=admin).status_code
        == 200
    )
    assert client.post(f"{url}/deactivate", headers=admin).status_code == 200

    db.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED
    assert booking.service_id == service.id
    assert (booking.price_amount, booking.duration_minutes) == (60000, 30)  # the snapshot
