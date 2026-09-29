"""/providers against a real PostgreSQL (P3.3)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, BookingStatus, Provider, ProviderService, Service, User

PROVIDERS = "/api/v1/providers"
VALID = {"name": "Jasur", "bio": "Ten years of classic cuts."}


def _service(db: Session, name="Haircut", active=True) -> Service:
    service = Service(name=name, duration_minutes=30, price=60000, is_active=active)
    db.add(service)
    db.flush()
    return service


def _provider(db: Session, name="Jasur", active=True, offers=()) -> Provider:
    provider = Provider(name=name, is_active=active)
    db.add(provider)
    db.flush()
    for service in offers:
        db.add(ProviderService(provider_id=provider.id, service_id=service.id))
    db.flush()
    return provider


def _offered(db: Session, provider: Provider) -> set[int]:
    query = select(ProviderService.service_id).where(ProviderService.provider_id == provider.id)
    return set(db.scalars(query))


# --- create ----------------------------------------------------------------


def test_admin_creates_a_provider_who_offers_nothing_yet(client, admin, db):
    response = client.post(PROVIDERS, json=VALID, headers=admin)

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Jasur"
    assert body["bio"] == "Ten years of classic cuts."
    assert body["is_active"] is True
    assert body["services"] == []
    assert db.get(Provider, body["id"]).name == "Jasur"


def test_create_trims_the_name_and_turns_a_blank_bio_into_none(client, admin):
    response = client.post(PROVIDERS, json={"name": "  Jasur ", "bio": "  "}, headers=admin)
    assert response.status_code == 201
    assert response.json()["name"] == "Jasur"
    assert response.json()["bio"] is None


def test_customer_and_anonymous_cannot_create(client, customer):
    assert client.post(PROVIDERS, json=VALID, headers=customer).status_code == 403
    assert client.post(PROVIDERS, json=VALID).status_code == 401


@pytest.mark.parametrize(
    "body",
    [{}, {"name": ""}, {"name": "   "}, {"name": "x" * 101}, {"name": "A", "bio": "x" * 1001}],
)
def test_invalid_input_is_a_validation_error(client, admin, db, body):
    response = client.post(PROVIDERS, json=body, headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert db.scalar(select(Provider)) is None


# --- list and read ---------------------------------------------------------


def test_public_list_shows_active_providers_with_their_active_services(client, db):
    haircut, shave = _service(db, "Haircut"), _service(db, "Shave")
    retired = _service(db, "Retired special", active=False)
    _provider(db, "Jasur", offers=[shave, haircut, retired])
    _provider(db, "Bekzod", active=False)
    _provider(db, "Aziz")

    body = client.get(PROVIDERS).json()  # anonymous

    assert [p["name"] for p in body["items"]] == ["Aziz", "Jasur"]  # alphabetical, no Bekzod
    assert (body["total"], body["limit"], body["offset"]) == (2, 20, 0)
    jasur = body["items"][1]
    assert [s["name"] for s in jasur["services"]] == ["Haircut", "Shave"]  # no inactive one
    assert body["items"][0]["services"] == []


def test_list_can_be_filtered_by_service(client, db):
    haircut, shave = _service(db, "Haircut"), _service(db, "Shave")
    _provider(db, "Jasur", offers=[haircut, shave])
    _provider(db, "Aziz", offers=[shave])
    _provider(db, "Bekzod", active=False, offers=[haircut])

    haircut_people = client.get(PROVIDERS, params={"service_id": haircut.id}).json()
    shave_people = client.get(PROVIDERS, params={"service_id": shave.id}).json()

    assert [p["name"] for p in haircut_people["items"]] == ["Jasur"]  # Bekzod is inactive
    assert haircut_people["total"] == 1
    assert [p["name"] for p in shave_people["items"]] == ["Aziz", "Jasur"]


def test_filtering_by_an_unknown_or_inactive_service_finds_nobody(client, admin, db):
    retired = _service(db, "Retired", active=False)
    _provider(db, "Jasur", offers=[retired])

    assert client.get(PROVIDERS, params={"service_id": 999999}).json()["items"] == []
    assert client.get(PROVIDERS, params={"service_id": retired.id}).json()["items"] == []
    # An admin looking at inactive things does see the link.
    found = client.get(
        PROVIDERS, params={"service_id": retired.id, "include_inactive": "true"}, headers=admin
    ).json()
    assert [p["name"] for p in found["items"]] == ["Jasur"]


def test_list_is_paginated_and_out_of_range_paging_is_422(client, db):
    for n in range(5):
        _provider(db, f"Provider {n}")

    page = client.get(PROVIDERS, params={"limit": 2, "offset": 3}).json()

    assert [p["name"] for p in page["items"]] == ["Provider 3", "Provider 4"]
    assert page["total"] == 5
    assert client.get(PROVIDERS, params={"limit": 101}).status_code == 422


def test_admin_can_list_inactive_providers_and_others_are_refused(client, admin, customer, db):
    _provider(db, "Jasur")
    _provider(db, "Bekzod", active=False)
    params = {"include_inactive": "true"}

    body = client.get(PROVIDERS, params=params, headers=admin).json()
    assert [p["name"] for p in body["items"]] == ["Bekzod", "Jasur"]
    assert client.get(PROVIDERS, params=params).status_code == 401
    assert client.get(PROVIDERS, params=params, headers=customer).status_code == 403


def test_read_one_includes_offered_services(client, db):
    haircut = _service(db)
    provider = _provider(db, offers=[haircut])

    body = client.get(f"{PROVIDERS}/{provider.id}").json()

    assert body["name"] == "Jasur"
    assert [s["id"] for s in body["services"]] == [haircut.id]


def test_an_inactive_provider_is_404_for_the_public_and_customers_but_not_admins(
    client, admin, customer, db
):
    provider = _provider(db, active=False)
    url = f"{PROVIDERS}/{provider.id}"

    assert client.get(url).status_code == 404
    assert client.get(url, headers=customer).status_code == 404
    assert client.get(url, headers=admin).status_code == 200


def test_admin_sees_inactive_services_a_provider_offers_and_customers_do_not(client, admin, db):
    retired = _service(db, "Retired", active=False)
    provider = _provider(db, offers=[retired])
    url = f"{PROVIDERS}/{provider.id}"

    assert client.get(url).json()["services"] == []
    seen = client.get(url, headers=admin).json()["services"]
    assert [(s["name"], s["is_active"]) for s in seen] == [("Retired", False)]


def test_unknown_provider_is_404_in_the_error_envelope(client):
    response = client.get(f"{PROVIDERS}/999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- update, deactivate, activate ------------------------------------------


def test_admin_updates_only_the_fields_sent(client, admin, db):
    provider = _provider(db, "Jasur")
    provider.bio = "Old bio"
    db.flush()
    url = f"{PROVIDERS}/{provider.id}"

    renamed = client.patch(url, json={"name": " Jasur K. "}, headers=admin).json()
    assert (renamed["name"], renamed["bio"]) == ("Jasur K.", "Old bio")
    assert client.patch(url, json={"bio": None}, headers=admin).json()["bio"] is None


def test_update_validation_and_authorisation(client, admin, customer, db):
    provider = _provider(db)
    url = f"{PROVIDERS}/{provider.id}"

    assert client.patch(url, json={"name": None}, headers=admin).status_code == 422
    assert client.patch(url, json={"name": "  "}, headers=admin).status_code == 422
    assert client.patch(url, json={}, headers=admin).status_code == 422
    assert client.patch(f"{PROVIDERS}/999999", json={"name": "A"}, headers=admin).status_code == 404
    assert client.patch(url, json={"name": "A"}, headers=customer).status_code == 403
    assert client.patch(url, json={"name": "A"}).status_code == 401
    assert db.get(Provider, provider.id).name == "Jasur"


def test_deactivating_hides_the_provider_and_activating_shows_them_again(client, admin, db):
    provider = _provider(db)
    url = f"{PROVIDERS}/{provider.id}"

    assert client.post(f"{url}/deactivate", headers=admin).json()["is_active"] is False
    assert client.get(url).status_code == 404
    assert client.get(PROVIDERS).json()["items"] == []

    assert client.post(f"{url}/activate", headers=admin).json()["is_active"] is True
    assert client.get(url).status_code == 200


def test_repeating_deactivate_or_activate_is_harmless(client, admin, db):
    url = f"{PROVIDERS}/{_provider(db).id}"
    assert client.post(f"{url}/activate", headers=admin).status_code == 200
    assert client.post(f"{url}/deactivate", headers=admin).status_code == 200
    assert client.post(f"{url}/deactivate", headers=admin).status_code == 200


def test_activation_and_deactivation_are_admin_only_and_404_for_unknown(
    client, admin, customer, db
):
    url = f"{PROVIDERS}/{_provider(db).id}"
    assert client.post(f"{url}/deactivate", headers=customer).status_code == 403
    assert client.post(f"{url}/deactivate").status_code == 401
    assert client.post(f"{PROVIDERS}/999999/activate", headers=admin).status_code == 404


def _future_booking(db: Session, provider: Provider, service: Service) -> Booking:
    customer = User(email="ali@example.uz", password_hash="x", full_name="Ali")
    db.add(customer)
    db.flush()
    start = datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    booking = Booking(
        customer_id=customer.id,
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
    return booking


def test_deactivating_a_provider_or_changing_their_services_keeps_their_bookings(client, admin, db):
    haircut = _service(db)
    provider = _provider(db, offers=[haircut])
    booking = _future_booking(db, provider, haircut)
    url = f"{PROVIDERS}/{provider.id}"

    assert client.put(f"{url}/services", json={"service_ids": []}, headers=admin).status_code == 200
    assert client.post(f"{url}/deactivate", headers=admin).status_code == 200

    db.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED
    assert (booking.provider_id, booking.service_id) == (provider.id, haircut.id)


# --- offered services ------------------------------------------------------


def test_put_replaces_the_whole_set(client, admin, db):
    haircut, shave, beard = _service(db, "Haircut"), _service(db, "Shave"), _service(db, "Beard")
    provider = _provider(db, offers=[haircut, shave])

    response = client.put(
        f"{PROVIDERS}/{provider.id}/services",
        json={"service_ids": [shave.id, beard.id]},
        headers=admin,
    )

    assert response.status_code == 200
    assert [s["name"] for s in response.json()["services"]] == ["Beard", "Shave"]
    assert _offered(db, provider) == {shave.id, beard.id}  # Haircut removed, Beard added


def test_put_with_an_empty_list_clears_the_set_and_repeats_and_duplicates_are_harmless(
    client, admin, db
):
    haircut = _service(db)
    provider = _provider(db, offers=[haircut])
    url = f"{PROVIDERS}/{provider.id}/services"

    twice = client.put(url, json={"service_ids": [haircut.id, haircut.id]}, headers=admin)
    assert twice.status_code == 200 and len(twice.json()["services"]) == 1
    assert client.put(url, json={"service_ids": [haircut.id]}, headers=admin).status_code == 200
    assert client.put(url, json={"service_ids": []}, headers=admin).json()["services"] == []
    assert _offered(db, provider) == set()


def test_unknown_or_inactive_service_ids_are_refused_and_nothing_changes(client, admin, db):
    haircut = _service(db, "Haircut")
    retired = _service(db, "Retired", active=False)
    provider = _provider(db, offers=[haircut])

    response = client.put(
        f"{PROVIDERS}/{provider.id}/services",
        json={"service_ids": [retired.id, 999999, haircut.id]},
        headers=admin,
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "UNKNOWN_SERVICE"
    assert error["details"]["service_ids"] == sorted([retired.id, 999999])
    assert _offered(db, provider) == {haircut.id}  # untouched


def test_put_validation_authorisation_and_unknown_provider(client, admin, customer, db):
    provider = _provider(db)
    url = f"{PROVIDERS}/{provider.id}/services"

    assert client.put(url, json={}, headers=admin).status_code == 422
    assert client.put(url, json={"service_ids": ["a"]}, headers=admin).status_code == 422
    assert client.put(url, json={"service_ids": []}, headers=customer).status_code == 403
    assert client.put(url, json={"service_ids": []}).status_code == 401
    missing = client.put(f"{PROVIDERS}/999999/services", json={"service_ids": []}, headers=admin)
    assert missing.status_code == 404
