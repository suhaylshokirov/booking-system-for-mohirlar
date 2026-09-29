"""/providers/{id}/availability/rules against a real PostgreSQL (P4.2)."""

from datetime import time

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AvailabilityRule, Provider
from app.models.business_settings import BusinessSettings
from app.services import availability

MONDAY = {"weekday": 0, "start_time": "09:00", "end_time": "18:00"}


def _provider(db: Session, name="Jasur", active=True) -> Provider:
    provider = Provider(name=name, is_active=active)
    db.add(provider)
    db.flush()
    return provider


def _url(provider: Provider, suffix="") -> str:
    return f"/api/v1/providers/{provider.id}/availability/rules{suffix}"


def _rule(db: Session, provider: Provider, weekday=0, start=(9, 0), end=(18, 0)):
    rule = AvailabilityRule(
        provider_id=provider.id, weekday=weekday, start_time=time(*start), end_time=time(*end)
    )
    db.add(rule)
    db.flush()
    return rule


def _rules(db: Session, provider: Provider) -> list[AvailabilityRule]:
    return list(
        db.scalars(select(AvailabilityRule).where(AvailabilityRule.provider_id == provider.id))
    )


# --- create and list ---------------------------------------------------------


def test_admin_creates_a_rule(client, admin, db):
    provider = _provider(db)
    response = client.post(_url(provider), json=MONDAY, headers=admin)

    assert response.status_code == 201
    body = response.json()
    assert body["provider_id"] == provider.id
    assert (body["weekday"], body["start_time"], body["end_time"]) == (0, "09:00:00", "18:00:00")
    assert len(_rules(db, provider)) == 1


def test_public_list_is_sorted_by_weekday_then_start(client, db):
    provider = _provider(db)
    _rule(db, provider, weekday=2, start=(9, 0), end=(12, 0))
    _rule(db, provider, weekday=0, start=(14, 0), end=(18, 0))
    _rule(db, provider, weekday=0, start=(9, 0), end=(12, 0))

    response = client.get(_url(provider))

    assert response.status_code == 200
    assert [(r["weekday"], r["start_time"]) for r in response.json()] == [
        (0, "09:00:00"),
        (0, "14:00:00"),
        (2, "09:00:00"),
    ]


def test_list_only_shows_that_providers_rules(client, db):
    jasur, aziz = _provider(db), _provider(db, "Aziz")
    _rule(db, jasur)
    assert client.get(_url(aziz)).json() == []


def test_inactive_provider_rules_are_hidden_from_the_public_but_not_admins(client, admin, db):
    provider = _provider(db, active=False)
    _rule(db, provider)

    assert client.get(_url(provider)).status_code == 404
    assert len(client.get(_url(provider), headers=admin).json()) == 1


def test_unknown_provider_is_404_everywhere(client, admin):
    url = "/api/v1/providers/999/availability/rules"
    assert client.get(url).status_code == 404
    assert client.post(url, json=MONDAY, headers=admin).status_code == 404


def test_only_admins_can_write(client, customer, db):
    provider = _provider(db)
    rule = _rule(db, provider)
    for method, url, body in [
        ("post", _url(provider), MONDAY),
        ("patch", _url(provider, f"/{rule.id}"), {"end_time": "17:00"}),
        ("delete", _url(provider, f"/{rule.id}"), None),
    ]:
        assert client.request(method, url, json=body).status_code == 401
        assert client.request(method, url, json=body, headers=customer).status_code == 403
    assert len(_rules(db, provider)) == 1


# --- overlap -----------------------------------------------------------------


def test_overlapping_rule_is_409_and_names_the_other_rule(client, admin, db):
    provider = _provider(db)
    existing = _rule(db, provider, start=(9, 0), end=(12, 0))

    response = client.post(
        _url(provider), json={**MONDAY, "start_time": "11:00", "end_time": "14:00"}, headers=admin
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "AVAILABILITY_OVERLAP"
    assert error["details"]["conflicting_rule"]["id"] == existing.id
    assert len(_rules(db, provider)) == 1


@pytest.mark.parametrize(
    "start,end",
    [("09:00", "12:00"), ("10:00", "11:00"), ("08:00", "13:00"), ("08:00", "09:15")],
    ids=["identical", "inside", "around", "one-slot-into-the-start"],
)
def test_every_shape_of_overlap_is_refused(client, admin, db, start, end):
    provider = _provider(db)
    _rule(db, provider, start=(9, 0), end=(12, 0))
    body = {**MONDAY, "start_time": start, "end_time": end}
    assert client.post(_url(provider), json=body, headers=admin).status_code == 409


def test_adjacent_rules_are_allowed(client, admin, db):
    provider = _provider(db)
    _rule(db, provider, start=(9, 0), end=(12, 0))

    for window in [("12:00", "18:00"), ("08:00", "09:00")]:
        body = {**MONDAY, "start_time": window[0], "end_time": window[1]}
        assert client.post(_url(provider), json=body, headers=admin).status_code == 201


def test_same_hours_on_another_weekday_or_provider_do_not_overlap(client, admin, db):
    jasur, aziz = _provider(db), _provider(db, "Aziz")
    _rule(db, jasur)

    assert client.post(_url(jasur), json={**MONDAY, "weekday": 1}, headers=admin).status_code == 201
    assert client.post(_url(aziz), json=MONDAY, headers=admin).status_code == 201


def test_database_exclusion_constraint_is_the_backstop(client, admin, db, monkeypatch):
    """If the friendly pre-check misses (a race), the constraint still says no, as a 409."""
    provider = _provider(db)
    _rule(db, provider, start=(9, 0), end=(12, 0))
    monkeypatch.setattr(availability, "_find_overlap", lambda *args, **kwargs: None)

    response = client.post(
        _url(provider), json={**MONDAY, "start_time": "10:00", "end_time": "11:00"}, headers=admin
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AVAILABILITY_OVERLAP"
    assert len(_rules(db, provider)) == 1  # the failed insert left nothing behind


# --- validation --------------------------------------------------------------


@pytest.mark.parametrize("start,end", [("09:10", "18:00"), ("09:00", "17:50"), ("09:07", "18:00")])
def test_misaligned_times_are_422_with_the_granularity(client, admin, db, start, end):
    provider = _provider(db)  # default granularity: 15 minutes
    response = client.post(
        _url(provider), json={**MONDAY, "start_time": start, "end_time": end}, headers=admin
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "MISALIGNED_TIME"
    assert error["details"]["slot_granularity_minutes"] == 15
    assert _rules(db, provider) == []


def test_alignment_follows_the_configured_granularity(client, admin, db):
    provider = _provider(db)
    db.execute(
        BusinessSettings.__table__.insert().values(id=1, name="Navbat", slot_granularity_minutes=30)
    )
    body = {**MONDAY, "start_time": "09:15"}
    assert client.post(_url(provider), json=body, headers=admin).status_code == 422
    assert (
        client.post(_url(provider), json={**body, "start_time": "09:30"}, headers=admin).status_code
        == 201
    )


@pytest.mark.parametrize(
    "body",
    [
        {**MONDAY, "weekday": 7},
        {**MONDAY, "weekday": -1},
        {**MONDAY, "end_time": "09:00"},  # empty window
        {**MONDAY, "start_time": "18:00", "end_time": "09:00"},  # backwards
        {**MONDAY, "start_time": "09:00:30"},  # seconds
        {**MONDAY, "start_time": "09:00+05:00"},  # offset
        {**MONDAY, "end_time": "24:00"},
        {**MONDAY, "end_time": "nine"},
        {"weekday": 0, "start_time": "09:00"},
        {},
    ],
)
def test_malformed_input_is_a_validation_error(client, admin, db, body):
    provider = _provider(db)
    response = client.post(_url(provider), json=body, headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert _rules(db, provider) == []


# --- update ------------------------------------------------------------------


def test_admin_changes_a_rule(client, admin, db):
    provider = _provider(db)
    rule = _rule(db, provider)

    response = client.patch(
        _url(provider, f"/{rule.id}"), json={"end_time": "19:00"}, headers=admin
    )

    assert response.status_code == 200
    assert response.json()["end_time"] == "19:00:00"
    assert response.json()["start_time"] == "09:00:00"


def test_a_rule_can_grow_over_its_own_old_hours(client, admin, db):
    """Editing must not count the rule as overlapping itself."""
    provider = _provider(db)
    rule = _rule(db, provider, start=(9, 0), end=(12, 0))
    response = client.patch(
        _url(provider, f"/{rule.id}"), json={"end_time": "13:00"}, headers=admin
    )
    assert response.status_code == 200


def test_moving_a_rule_onto_another_is_refused_and_leaves_it_unchanged(client, admin, db):
    provider = _provider(db)
    _rule(db, provider, weekday=0, start=(9, 0), end=(12, 0))
    other_day = _rule(db, provider, weekday=1, start=(10, 0), end=(11, 0))

    response = client.patch(_url(provider, f"/{other_day.id}"), json={"weekday": 0}, headers=admin)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AVAILABILITY_OVERLAP"
    db.refresh(other_day)
    assert other_day.weekday == 1


def test_update_that_leaves_end_before_start_is_422(client, admin, db):
    provider = _provider(db)
    rule = _rule(db, provider, start=(9, 0), end=(18, 0))

    response = client.patch(
        _url(provider, f"/{rule.id}"), json={"end_time": "08:00"}, headers=admin
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TIME_RANGE"


def test_update_misaligned_and_empty_bodies_are_422(client, admin, db):
    provider = _provider(db)
    rule = _rule(db, provider)
    url = _url(provider, f"/{rule.id}")

    misaligned = client.patch(url, json={"start_time": "09:10"}, headers=admin)
    assert misaligned.json()["error"]["code"] == "MISALIGNED_TIME"
    for body in ({}, {"weekday": None}):
        assert client.patch(url, json=body, headers=admin).status_code == 422


def test_another_providers_rule_id_is_404(client, admin, db):
    jasur, aziz = _provider(db), _provider(db, "Aziz")
    rule = _rule(db, jasur)

    assert (
        client.patch(
            _url(aziz, f"/{rule.id}"), json={"end_time": "17:00"}, headers=admin
        ).status_code
        == 404
    )
    assert client.delete(_url(aziz, f"/{rule.id}"), headers=admin).status_code == 404
    assert len(_rules(db, jasur)) == 1


# --- delete ------------------------------------------------------------------


def test_admin_deletes_a_rule(client, admin, db):
    provider = _provider(db)
    rule = _rule(db, provider)

    response = client.delete(_url(provider, f"/{rule.id}"), headers=admin)

    assert response.status_code == 204
    assert _rules(db, provider) == []
    assert client.delete(_url(provider, f"/{rule.id}"), headers=admin).status_code == 404
