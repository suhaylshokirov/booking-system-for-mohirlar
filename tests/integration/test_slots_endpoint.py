"""GET /slots (P5.3).

Frozen clock: 2026-10-01 07:00 UTC (12:00 Tashkent). 2026-10-05 is a Monday;
09:00 local is 04:00 UTC. Default settings: 15 min grid, 60 day horizon.
"""

from datetime import time

import pytest

from app.models import AvailabilityRule, Provider, ProviderService, Service

SLOTS = "/api/v1/slots"


@pytest.fixture
def setup(db):
    service = Service(name="Haircut", duration_minutes=30, price=60000)
    jasur, aziz = Provider(name="Jasur"), Provider(name="Aziz")
    db.add_all([service, jasur, aziz])
    db.flush()
    for provider in (jasur, aziz):
        db.add(ProviderService(provider_id=provider.id, service_id=service.id))
    db.add(AvailabilityRule(provider_id=jasur.id, weekday=0, start_time=time(9), end_time=time(10)))
    db.flush()
    return service, jasur, aziz


def test_public_happy_path_lists_slots_grouped_by_provider(client, setup):
    service, jasur, _ = setup
    response = client.get(SLOTS, params={"service_id": service.id, "date": "2026-10-05"})

    assert response.status_code == 200  # no login needed
    body = response.json()
    assert body["date"] == "2026-10-05"
    assert body["timezone"] == "Asia/Tashkent"
    assert body["service"] == {
        "id": service.id,
        "name": "Haircut",
        "duration_minutes": 30,
        "price": 60000,
    }
    assert [p["provider"]["name"] for p in body["providers"]] == ["Aziz", "Jasur"]
    assert body["providers"][0]["slots"] == []
    assert body["providers"][1]["slots"] == [
        {"start_at": "2026-10-05T04:00:00Z", "end_at": "2026-10-05T04:30:00Z"},
        {"start_at": "2026-10-05T04:15:00Z", "end_at": "2026-10-05T04:45:00Z"},
        {"start_at": "2026-10-05T04:30:00Z", "end_at": "2026-10-05T05:00:00Z"},
    ]


def test_provider_filter_returns_one_provider(client, setup):
    service, jasur, _ = setup
    response = client.get(
        SLOTS, params={"service_id": service.id, "date": "2026-10-05", "provider_id": jasur.id}
    )
    assert [p["provider"]["id"] for p in response.json()["providers"]] == [jasur.id]


def test_a_date_before_today_is_422_date_out_of_range(client, setup):
    response = client.get(SLOTS, params={"service_id": setup[0].id, "date": "2026-09-30"})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "DATE_OUT_OF_RANGE"
    assert error["details"] == {"earliest": "2026-10-01", "latest": "2026-11-30"}


def test_today_and_the_last_horizon_day_are_accepted_and_the_day_after_is_not(client, setup):
    params = {"service_id": setup[0].id}
    assert client.get(SLOTS, params={**params, "date": "2026-10-01"}).status_code == 200
    assert client.get(SLOTS, params={**params, "date": "2026-11-30"}).status_code == 200
    beyond = client.get(SLOTS, params={**params, "date": "2026-12-01"})
    assert (beyond.status_code, beyond.json()["error"]["code"]) == (422, "DATE_OUT_OF_RANGE")


def test_a_malformed_date_or_missing_service_id_is_422_validation_error(client, setup):
    bad_date = client.get(SLOTS, params={"service_id": setup[0].id, "date": "05/10/2026"})
    missing = client.get(SLOTS, params={"date": "2026-10-05"})
    assert bad_date.status_code == missing.status_code == 422
    assert bad_date.json()["error"]["code"] == missing.json()["error"]["code"] == "VALIDATION_ERROR"


def test_unknown_service_and_unknown_provider_are_404(client, setup):
    service = setup[0]
    unknown_service = client.get(SLOTS, params={"service_id": 9999, "date": "2026-10-05"})
    unknown_provider = client.get(
        SLOTS, params={"service_id": service.id, "date": "2026-10-05", "provider_id": 9999}
    )
    assert unknown_service.status_code == unknown_provider.status_code == 404
    assert unknown_service.json()["error"]["code"] == "NOT_FOUND"


def test_a_provider_who_does_not_offer_the_service_is_422(client, setup, db):
    service, _, _ = setup
    other = Service(name="Beard trim", duration_minutes=15, price=30000)
    db.add(other)
    db.flush()
    response = client.get(
        SLOTS, params={"service_id": other.id, "date": "2026-10-05", "provider_id": setup[1].id}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PROVIDER_DOES_NOT_OFFER_SERVICE"
