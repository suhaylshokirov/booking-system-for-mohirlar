"""/providers/{id}/availability/exceptions against a real PostgreSQL (P4.3).

The frozen clock is Thursday 2026-10-01 12:00 in Tashkent, so "today" is 2026-10-01.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models import (
    AvailabilityException,
    AvailabilityRule,
    Booking,
    BookingStatus,
    Provider,
    Service,
    User,
)
from app.services import availability

DAY_OFF = {"date": "2026-10-12", "reason": "Public holiday"}
CUSTOM = {"date": "2026-10-13", "start_time": "12:00", "end_time": "16:00"}


def _provider(db: Session, name="Jasur", active=True) -> Provider:
    provider = Provider(name=name, is_active=active)
    db.add(provider)
    db.flush()
    return provider


def _url(provider: Provider, suffix="") -> str:
    return f"/api/v1/providers/{provider.id}/availability/exceptions{suffix}"


def _exception(db: Session, provider: Provider, day: date, start=None, end=None):
    row = AvailabilityException(provider_id=provider.id, date=day, start_time=start, end_time=end)
    db.add(row)
    db.flush()
    return row


def _rows(db: Session, provider: Provider) -> list[AvailabilityException]:
    query = select(AvailabilityException).where(AvailabilityException.provider_id == provider.id)
    return list(db.scalars(query))


# --- create ------------------------------------------------------------------


def test_admin_marks_a_day_off(client, admin, db):
    provider = _provider(db)
    response = client.post(_url(provider), json=DAY_OFF, headers=admin)

    assert response.status_code == 201
    body = response.json()
    assert body["date"] == "2026-10-12"
    assert (body["start_time"], body["end_time"]) == (None, None)
    assert body["is_day_off"] is True
    assert body["reason"] == "Public holiday"
    assert len(_rows(db, provider)) == 1


def test_admin_sets_custom_hours(client, admin, db):
    provider = _provider(db)
    response = client.post(_url(provider), json=CUSTOM, headers=admin)

    assert response.status_code == 201
    body = response.json()
    assert (body["start_time"], body["end_time"]) == ("12:00:00", "16:00:00")
    assert body["is_day_off"] is False
    assert body["reason"] is None


def test_an_exception_replaces_rules_without_touching_them(client, admin, db):
    """The rule table is left alone; the slot code (P5) lets the exception win."""
    provider = _provider(db)
    db.add(
        AvailabilityRule(provider_id=provider.id, weekday=0, start_time=time(9), end_time=time(18))
    )
    db.flush()

    client.post(_url(provider), json={"date": "2026-10-12"}, headers=admin)  # a Monday

    assert db.scalar(select(AvailabilityRule)) is not None


def test_today_is_allowed_but_yesterday_is_not(client, admin, db):
    provider = _provider(db)
    assert (
        client.post(_url(provider), json={"date": "2026-10-01"}, headers=admin).status_code == 201
    )

    response = client.post(_url(provider), json={"date": "2026-09-30"}, headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATE_IN_PAST"
    assert response.json()["error"]["details"]["today"] == "2026-10-01"


def test_today_is_the_business_date_not_the_utc_date(client, admin, db, frozen_clock):
    """20:00 UTC on 1 Oct is already 01:00 on 2 Oct in Tashkent, so 1 Oct is over."""
    provider = _provider(db)
    frozen_clock.advance(timedelta(hours=13))
    # The old token would have expired by now, so mint a fresh one for the same admin.
    admin_id = db.scalar(select(User.id))
    fresh = {"Authorization": f"Bearer {create_access_token(admin_id, frozen_clock.now())}"}

    response = client.post(_url(provider), json={"date": "2026-10-01"}, headers=fresh)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "DATE_IN_PAST"
    assert (
        client.post(_url(provider), json={"date": "2026-10-02"}, headers=fresh).status_code == 201
    )


def test_second_exception_for_a_date_is_409(client, admin, db):
    provider = _provider(db)
    first = _exception(db, provider, date(2026, 10, 12))

    response = client.post(_url(provider), json=CUSTOM | {"date": "2026-10-12"}, headers=admin)

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "AVAILABILITY_EXCEPTION_EXISTS"
    assert error["details"]["exception_id"] == first.id
    assert len(_rows(db, provider)) == 1


def test_the_same_date_for_another_provider_is_fine(client, admin, db):
    jasur, aziz = _provider(db), _provider(db, "Aziz")
    _exception(db, jasur, date(2026, 10, 12))
    assert client.post(_url(aziz), json=DAY_OFF, headers=admin).status_code == 201


def test_unique_constraint_is_the_backstop(client, admin, db, monkeypatch):
    """With the pre-check blind (a race), the database still says no, as the same 409."""
    provider = _provider(db)
    _exception(db, provider, date(2026, 10, 12))
    monkeypatch.setattr(availability, "_find_exception_on", lambda *args, **kwargs: None)

    response = client.post(_url(provider), json=DAY_OFF, headers=admin)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "AVAILABILITY_EXCEPTION_EXISTS"
    assert len(_rows(db, provider)) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"date": "2026-10-12", "start_time": "12:00"},  # only one time
        {"date": "2026-10-12", "end_time": "16:00"},
        {"date": "2026-10-12", "start_time": "16:00", "end_time": "12:00"},
        {"date": "2026-10-12", "start_time": "12:00", "end_time": "12:00"},
        {"date": "2026-10-12", "start_time": "12:00:30", "end_time": "16:00"},
        {"date": "12/10/2026"},
        {"date": "2026-10-12", "reason": "x" * 201},
        {"start_time": "12:00", "end_time": "16:00"},
        {},
    ],
)
def test_malformed_input_is_a_validation_error(client, admin, db, body):
    provider = _provider(db)
    response = client.post(_url(provider), json=body, headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert _rows(db, provider) == []


def test_custom_hours_must_sit_on_the_slot_grid(client, admin, db):
    provider = _provider(db)  # default 15-minute grid
    response = client.post(_url(provider), json=CUSTOM | {"start_time": "12:10"}, headers=admin)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "MISALIGNED_TIME"


def test_blank_reason_becomes_none(client, admin, db):
    provider = _provider(db)
    response = client.post(_url(provider), json=DAY_OFF | {"reason": "   "}, headers=admin)
    assert response.json()["reason"] is None


# --- existing bookings -------------------------------------------------------


def test_an_exception_on_a_date_with_bookings_keeps_the_bookings(client, admin, db):
    provider = _provider(db)
    customer = User(email="c@example.com", password_hash="x", full_name="C")
    service = Service(name="Haircut", duration_minutes=30, price=60000)
    db.add_all([customer, service])
    db.flush()
    start = datetime(2026, 10, 12, 5, 0, tzinfo=UTC)  # 10:00 Tashkent
    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_id=service.id,
        start_at=start,
        end_at=start + timedelta(minutes=30),
        status=BookingStatus.CONFIRMED,
        price_amount=60000,
        duration_minutes=30,
    )
    db.add(booking)
    db.flush()

    response = client.post(_url(provider), json=DAY_OFF, headers=admin)

    assert response.status_code == 201
    db.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED


# --- list, permissions -------------------------------------------------------


def test_list_is_admin_only_and_sorted_by_date(client, admin, customer, db):
    provider = _provider(db)
    _exception(db, provider, date(2026, 10, 20))
    _exception(db, provider, date(2026, 9, 1))  # past ones stay listed
    _exception(db, provider, date(2026, 10, 12))

    response = client.get(_url(provider), headers=admin)

    assert [row["date"] for row in response.json()] == ["2026-09-01", "2026-10-12", "2026-10-20"]
    assert client.get(_url(provider)).status_code == 401
    assert client.get(_url(provider), headers=customer).status_code == 403


def test_only_admins_can_write(client, customer, db):
    provider = _provider(db)
    row = _exception(db, provider, date(2026, 10, 12))
    for method, url, body in [
        ("post", _url(provider), DAY_OFF),
        ("patch", _url(provider, f"/{row.id}"), {"reason": "x"}),
        ("delete", _url(provider, f"/{row.id}"), None),
    ]:
        assert client.request(method, url, json=body).status_code == 401
        assert client.request(method, url, json=body, headers=customer).status_code == 403
    assert len(_rows(db, provider)) == 1


def test_unknown_provider_is_404(client, admin):
    url = "/api/v1/providers/999/availability/exceptions"
    assert client.get(url, headers=admin).status_code == 404
    assert client.post(url, json=DAY_OFF, headers=admin).status_code == 404


# --- update ------------------------------------------------------------------


def test_day_off_becomes_custom_hours_and_back(client, admin, db):
    provider = _provider(db)
    row = _exception(db, provider, date(2026, 10, 12))
    url = _url(provider, f"/{row.id}")

    opened = client.patch(url, json={"start_time": "10:00", "end_time": "14:00"}, headers=admin)
    assert (opened.json()["start_time"], opened.json()["is_day_off"]) == ("10:00:00", False)

    closed = client.patch(url, json={"start_time": None, "end_time": None}, headers=admin)
    assert closed.status_code == 200
    assert (closed.json()["start_time"], closed.json()["is_day_off"]) == (None, True)


def test_update_can_move_the_date_and_clear_the_reason(client, admin, db):
    provider = _provider(db)
    row = _exception(db, provider, date(2026, 10, 12))
    row.reason = "Holiday"
    db.flush()

    response = client.patch(
        _url(provider, f"/{row.id}"), json={"date": "2026-10-14", "reason": None}, headers=admin
    )

    assert response.status_code == 200
    assert (response.json()["date"], response.json()["reason"]) == ("2026-10-14", None)


def test_update_onto_a_taken_date_is_409_and_changes_nothing(client, admin, db):
    provider = _provider(db)
    _exception(db, provider, date(2026, 10, 12))
    other = _exception(db, provider, date(2026, 10, 13))

    response = client.patch(
        _url(provider, f"/{other.id}"), json={"date": "2026-10-12"}, headers=admin
    )

    assert response.status_code == 409
    db.refresh(other)
    assert other.date == date(2026, 10, 13)


def test_update_cannot_move_to_the_past_or_edit_a_past_exception(client, admin, db):
    provider = _provider(db)
    future = _exception(db, provider, date(2026, 10, 12))
    past = _exception(db, provider, date(2026, 9, 1))

    moved = client.patch(
        _url(provider, f"/{future.id}"), json={"date": "2026-09-30"}, headers=admin
    )
    edited = client.patch(_url(provider, f"/{past.id}"), json={"reason": "x"}, headers=admin)

    assert moved.json()["error"]["code"] == "DATE_IN_PAST"
    assert edited.json()["error"]["code"] == "DATE_IN_PAST"


def test_update_leaving_one_time_set_is_422(client, admin, db):
    provider = _provider(db)
    row = _exception(db, provider, date(2026, 10, 12))  # a day off

    response = client.patch(
        _url(provider, f"/{row.id}"), json={"start_time": "10:00"}, headers=admin
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_TIME_RANGE"


def test_update_bad_bodies_are_422(client, admin, db):
    provider = _provider(db)
    row = _exception(db, provider, date(2026, 10, 12))
    for body in ({}, {"date": None}):
        assert (
            client.patch(_url(provider, f"/{row.id}"), json=body, headers=admin).status_code == 422
        )


def test_another_providers_exception_id_is_404(client, admin, db):
    jasur, aziz = _provider(db), _provider(db, "Aziz")
    row = _exception(db, jasur, date(2026, 10, 12))

    assert (
        client.patch(_url(aziz, f"/{row.id}"), json={"reason": "x"}, headers=admin).status_code
        == 404
    )
    assert client.delete(_url(aziz, f"/{row.id}"), headers=admin).status_code == 404
    assert len(_rows(db, jasur)) == 1


# --- delete ------------------------------------------------------------------


def test_admin_deletes_an_exception_even_a_past_one(client, admin, db):
    provider = _provider(db)
    past = _exception(db, provider, date(2026, 9, 1))

    assert client.delete(_url(provider, f"/{past.id}"), headers=admin).status_code == 204
    assert _rows(db, provider) == []
    assert client.delete(_url(provider, f"/{past.id}"), headers=admin).status_code == 404
