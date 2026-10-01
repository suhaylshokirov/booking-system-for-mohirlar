"""/providers against a real PostgreSQL (P3.3)."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Booking, BookingStatus, Provider, ProviderService, Service, User

PROVIDERS = "/api/v1/providers"


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


# --- there is no create endpoint --------------------------------------------


def test_providers_cannot_be_created_through_the_api(client, barber, customer):
    """A provider exists because a barber account was created for them (ADR 0010)."""
    body = {"name": "Jasur"}
    assert client.post(PROVIDERS, json=body, headers=barber).status_code == 405
    assert client.post(PROVIDERS, json=body, headers=customer).status_code == 405
    assert client.post(PROVIDERS, json=body).status_code == 405


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


def test_filtering_by_an_unknown_or_inactive_service_finds_nobody(client, barber, db):
    retired = _service(db, "Retired", active=False)
    _provider(db, "Jasur", offers=[retired])

    assert client.get(PROVIDERS, params={"service_id": 999999}).json()["items"] == []
    assert client.get(PROVIDERS, params={"service_id": retired.id}).json()["items"] == []
    # A barber looking at inactive things does see the link.
    found = client.get(
        PROVIDERS, params={"service_id": retired.id, "include_inactive": "true"}, headers=barber
    ).json()
    assert [p["name"] for p in found["items"]] == ["Jasur"]


def test_list_is_paginated_and_out_of_range_paging_is_422(client, db):
    for n in range(5):
        _provider(db, f"Provider {n}")

    page = client.get(PROVIDERS, params={"limit": 2, "offset": 3}).json()

    assert [p["name"] for p in page["items"]] == ["Provider 3", "Provider 4"]
    assert page["total"] == 5
    assert client.get(PROVIDERS, params={"limit": 101}).status_code == 422


def test_barber_can_list_inactive_providers_and_others_are_refused(client, barber, customer, db):
    _provider(db, "Jasur")
    _provider(db, "Bekzod", active=False)
    params = {"include_inactive": "true"}

    body = client.get(PROVIDERS, params=params, headers=barber).json()
    assert [p["name"] for p in body["items"]] == ["Barber", "Bekzod", "Jasur"]
    assert client.get(PROVIDERS, params=params).status_code == 401
    assert client.get(PROVIDERS, params=params, headers=customer).status_code == 403


def test_read_one_includes_offered_services(client, db):
    haircut = _service(db)
    provider = _provider(db, offers=[haircut])

    body = client.get(f"{PROVIDERS}/{provider.id}").json()

    assert body["name"] == "Jasur"
    assert [s["id"] for s in body["services"]] == [haircut.id]


def test_an_inactive_provider_is_404_for_the_public_and_customers_but_not_barbers(
    client, barber, customer, db
):
    provider = _provider(db, active=False)
    url = f"{PROVIDERS}/{provider.id}"

    assert client.get(url).status_code == 404
    assert client.get(url, headers=customer).status_code == 404
    assert client.get(url, headers=barber).status_code == 200


def test_barber_sees_inactive_services_a_provider_offers_and_customers_do_not(client, barber, db):
    retired = _service(db, "Retired", active=False)
    provider = _provider(db, offers=[retired])
    url = f"{PROVIDERS}/{provider.id}"

    assert client.get(url).json()["services"] == []
    seen = client.get(url, headers=barber).json()["services"]
    assert [(s["name"], s["is_active"]) for s in seen] == [("Retired", False)]


def test_unknown_provider_is_404_in_the_error_envelope(client):
    response = client.get(f"{PROVIDERS}/999999")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- update, deactivate, activate ------------------------------------------


def test_barber_updates_only_the_fields_sent(client, barber, db):
    provider = barber.provider
    provider.bio = "Old bio"
    db.flush()
    url = f"{PROVIDERS}/{provider.id}"

    renamed = client.patch(url, json={"name": " Jasur K. "}, headers=barber).json()
    assert (renamed["name"], renamed["bio"]) == ("Jasur K.", "Old bio")
    assert client.patch(url, json={"bio": None}, headers=barber).json()["bio"] is None


def test_update_validation_and_authorisation(client, barber, customer, db):
    provider = barber.provider
    url = f"{PROVIDERS}/{provider.id}"

    assert client.patch(url, json={"name": None}, headers=barber).status_code == 422
    assert client.patch(url, json={"name": "  "}, headers=barber).status_code == 422
    assert client.patch(url, json={}, headers=barber).status_code == 422
    assert client.patch(url, json={"name": "A"}, headers=customer).status_code == 403
    assert client.patch(url, json={"name": "A"}).status_code == 401
    assert db.get(Provider, provider.id).name == "Barber"


def test_a_barber_sets_a_phone_number_that_is_stored_and_shown_as_e164(client, barber):
    url = f"{PROVIDERS}/{barber.provider.id}"

    saved = client.patch(url, json={"phone": "+998 (90) 123-45-67"}, headers=barber).json()

    assert saved["phone"] == "+998901234567"
    assert client.get(url).json()["phone"] == "+998901234567"
    assert client.get(PROVIDERS).json()["items"][0]["phone"] == "+998901234567"


def test_a_phone_without_a_country_code_is_422_and_null_or_blank_clears_it(client, barber, db):
    url = f"{PROVIDERS}/{barber.provider.id}"
    client.patch(url, json={"phone": "+998901234567"}, headers=barber)

    refused = client.patch(url, json={"phone": "90 123 45 67"}, headers=barber)
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "VALIDATION_ERROR"
    assert db.get(Provider, barber.provider.id).phone == "+998901234567"

    assert client.patch(url, json={"phone": ""}, headers=barber).json()["phone"] is None
    client.patch(url, json={"phone": "+998901234567"}, headers=barber)
    assert client.patch(url, json={"phone": None}, headers=barber).json()["phone"] is None


def test_deactivating_hides_the_provider_and_activating_shows_them_again(client, barber, db):
    provider = barber.provider
    url = f"{PROVIDERS}/{provider.id}"

    assert client.post(f"{url}/deactivate", headers=barber).json()["is_active"] is False
    assert client.get(url).status_code == 404
    assert client.get(PROVIDERS).json()["items"] == []

    assert client.post(f"{url}/activate", headers=barber).json()["is_active"] is True
    assert client.get(url).status_code == 200


def test_repeating_deactivate_or_activate_is_harmless(client, barber, db):
    url = f"{PROVIDERS}/{barber.provider.id}"
    assert client.post(f"{url}/activate", headers=barber).status_code == 200
    assert client.post(f"{url}/deactivate", headers=barber).status_code == 200
    assert client.post(f"{url}/deactivate", headers=barber).status_code == 200


def test_activation_and_deactivation_are_for_the_barber_themselves(client, barber, customer, db):
    url = f"{PROVIDERS}/{barber.provider.id}"
    assert client.post(f"{url}/deactivate", headers=customer).status_code == 403
    assert client.post(f"{url}/deactivate").status_code == 401
    # Another provider's id, or none at all, is not the barber's own.
    assert client.post(f"{PROVIDERS}/999999/activate", headers=barber).status_code == 403


def test_a_barber_cannot_change_another_barbers_profile(client, barber, db):
    haircut = _service(db)
    other = _provider(db, "Aziz", offers=[haircut])
    url = f"{PROVIDERS}/{other.id}"

    assert client.patch(url, json={"name": "Hacked"}, headers=barber).status_code == 403
    assert client.post(f"{url}/deactivate", headers=barber).status_code == 403
    assert client.post(f"{url}/activate", headers=barber).status_code == 403
    response = client.put(f"{url}/services", json={"service_ids": []}, headers=barber)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
    db.refresh(other)
    assert (other.name, other.is_active) == ("Aziz", True)
    assert _offered(db, other) == {haircut.id}


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


def test_deactivating_a_provider_or_changing_their_services_keeps_their_bookings(
    client, barber, db
):
    haircut = _service(db)
    provider = barber.provider
    db.add(ProviderService(provider_id=provider.id, service_id=haircut.id))
    db.flush()
    booking = _future_booking(db, provider, haircut)
    url = f"{PROVIDERS}/{provider.id}"

    assert (
        client.put(f"{url}/services", json={"service_ids": []}, headers=barber).status_code == 200
    )
    assert client.post(f"{url}/deactivate", headers=barber).status_code == 200

    db.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED
    assert (booking.provider_id, booking.service_id) == (provider.id, haircut.id)


# --- offered services ------------------------------------------------------


def test_put_replaces_the_whole_set(client, barber, db):
    haircut, shave, beard = _service(db, "Haircut"), _service(db, "Shave"), _service(db, "Beard")
    provider = barber.provider
    for service in (haircut, shave):
        db.add(ProviderService(provider_id=provider.id, service_id=service.id))
    db.flush()

    response = client.put(
        f"{PROVIDERS}/{provider.id}/services",
        json={"service_ids": [shave.id, beard.id]},
        headers=barber,
    )

    assert response.status_code == 200
    assert [s["name"] for s in response.json()["services"]] == ["Beard", "Shave"]
    assert _offered(db, provider) == {shave.id, beard.id}  # Haircut removed, Beard added


def test_put_with_an_empty_list_clears_the_set_and_repeats_and_duplicates_are_harmless(
    client, barber, db
):
    haircut = _service(db)
    provider = barber.provider
    db.add(ProviderService(provider_id=provider.id, service_id=haircut.id))
    db.flush()
    url = f"{PROVIDERS}/{provider.id}/services"

    twice = client.put(url, json={"service_ids": [haircut.id, haircut.id]}, headers=barber)
    assert twice.status_code == 200 and len(twice.json()["services"]) == 1
    assert client.put(url, json={"service_ids": [haircut.id]}, headers=barber).status_code == 200
    assert client.put(url, json={"service_ids": []}, headers=barber).json()["services"] == []
    assert _offered(db, provider) == set()


def test_unknown_or_inactive_service_ids_are_refused_and_nothing_changes(client, barber, db):
    haircut = _service(db, "Haircut")
    retired = _service(db, "Retired", active=False)
    provider = barber.provider
    db.add(ProviderService(provider_id=provider.id, service_id=haircut.id))
    db.flush()

    response = client.put(
        f"{PROVIDERS}/{provider.id}/services",
        json={"service_ids": [retired.id, 999999, haircut.id]},
        headers=barber,
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "UNKNOWN_SERVICE"
    assert error["details"]["service_ids"] == sorted([retired.id, 999999])
    assert _offered(db, provider) == {haircut.id}  # untouched


def test_put_validation_authorisation_and_unknown_provider(client, barber, customer, db):
    provider = barber.provider
    url = f"{PROVIDERS}/{provider.id}/services"

    assert client.put(url, json={}, headers=barber).status_code == 422
    assert client.put(url, json={"service_ids": ["a"]}, headers=barber).status_code == 422
    assert client.put(url, json={"service_ids": []}, headers=customer).status_code == 403
    assert client.put(url, json={"service_ids": []}).status_code == 401
    missing = client.put(f"{PROVIDERS}/999999/services", json={"service_ids": []}, headers=barber)
    assert missing.status_code == 403  # not the barber's own provider
