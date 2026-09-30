"""Cancel / confirm / complete endpoints and the admin list (P7.3).

Frozen clock: 2026-10-01 07:00 UTC. The booking is 2026-10-05 10:00-10:30
Tashkent (05:00-05:30 UTC). The default cancellation cutoff is 2 hours, so a
customer can cancel a confirmed booking until 03:00 UTC that day.
"""

from datetime import datetime, time, timedelta

import pytest

from app.core.security import create_access_token, hash_password
from app.models import AvailabilityRule, Provider, ProviderService, Service, User, UserRole

TEN = "2026-10-05T05:00:00Z"
ELEVEN = "2026-10-05T06:00:00Z"
START = datetime.fromisoformat(TEN)
BASE = "/api/v1/bookings"


def make_user(db, email, role=UserRole.CUSTOMER) -> User:
    user = User(email=email, password_hash=hash_password("x"), full_name=email, role=role)
    db.add(user)
    db.flush()
    return user


def move_clock_to(clock, instant: datetime) -> None:
    clock.advance(instant - clock.now())


def headers(user: User, clock) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id, clock.now())}"}


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
def ali_user(db):
    return make_user(db, "ali@example.com")


@pytest.fixture
def boss_user(db):
    return make_user(db, "boss@example.com", UserRole.ADMIN)


@pytest.fixture
def ali(ali_user, frozen_clock):
    return headers(ali_user, frozen_clock)


@pytest.fixture
def bob(db, frozen_clock):
    return headers(make_user(db, "bob@example.com"), frozen_clock)


@pytest.fixture
def boss(boss_user, frozen_clock):
    return headers(boss_user, frozen_clock)


def book(client, setup, who, start=TEN) -> int:
    service, provider = setup
    response = client.post(
        BASE,
        json={"service_id": service.id, "provider_id": provider.id, "start_at": start},
        headers=who,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def error_code(response) -> str:
    return response.json()["error"]["code"]


# --- confirm --------------------------------------------------------------


def test_admin_confirms_a_pending_booking(client, setup, ali, boss):
    booking_id = book(client, setup, ali)

    response = client.post(f"{BASE}/{booking_id}/confirm", headers=boss)

    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


def test_customer_cannot_confirm_or_complete(client, setup, ali):
    booking_id = book(client, setup, ali)
    for action in ("confirm", "complete"):
        response = client.post(f"{BASE}/{booking_id}/{action}", headers=ali)
        assert response.status_code == 403
        assert error_code(response) == "FORBIDDEN"


def test_confirming_twice_is_invalid_transition(client, setup, ali, boss):
    booking_id = book(client, setup, ali)
    client.post(f"{BASE}/{booking_id}/confirm", headers=boss)

    response = client.post(f"{BASE}/{booking_id}/confirm", headers=boss)

    assert response.status_code == 409
    assert error_code(response) == "INVALID_TRANSITION"


# --- cancel ---------------------------------------------------------------


def test_customer_cancels_own_pending_booking_with_a_reason(client, setup, ali):
    booking_id = book(client, setup, ali)

    response = client.post(f"{BASE}/{booking_id}/cancel", json={"reason": " Ill "}, headers=ali)

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert response.json()["cancel_reason"] == "Ill"


def test_cancel_works_without_a_body(client, setup, ali):
    booking_id = book(client, setup, ali)
    assert client.post(f"{BASE}/{booking_id}/cancel", headers=ali).status_code == 200


def test_customer_cancelling_someone_elses_booking_is_404(client, setup, ali, bob):
    booking_id = book(client, setup, ali)

    response = client.post(f"{BASE}/{booking_id}/cancel", headers=bob)

    assert response.status_code == 404
    assert error_code(response) == "BOOKING_NOT_FOUND"


def test_cancelling_frees_the_slot_for_someone_else(client, setup, ali, bob):
    booking_id = book(client, setup, ali)
    client.post(f"{BASE}/{booking_id}/cancel", headers=ali)

    assert book(client, setup, bob) != booking_id


def test_customer_cancel_of_confirmed_booking_respects_the_cutoff(
    client, setup, ali_user, boss, frozen_clock
):
    booking_id = book(client, setup, headers(ali_user, frozen_clock))
    client.post(f"{BASE}/{booking_id}/confirm", headers=boss)

    move_clock_to(
        frozen_clock, START - timedelta(hours=2, seconds=-1)
    )  # one second past the cutoff
    late = client.post(f"{BASE}/{booking_id}/cancel", headers=headers(ali_user, frozen_clock))
    assert late.status_code == 409
    assert error_code(late) == "CANCELLATION_CUTOFF_PASSED"
    assert late.json()["error"]["details"]["cutoff_at"].startswith("2026-10-05T03:00:00")

    move_clock_to(
        frozen_clock, START - timedelta(hours=2)
    )  # exactly at the cutoff is still allowed
    ok = client.post(f"{BASE}/{booking_id}/cancel", headers=headers(ali_user, frozen_clock))
    assert ok.status_code == 200


def test_changing_the_cutoff_setting_changes_the_deadline(
    client, setup, ali_user, boss, frozen_clock
):
    booking_id = book(client, setup, headers(ali_user, frozen_clock))
    client.post(f"{BASE}/{booking_id}/confirm", headers=boss)
    assert (
        client.patch(
            "/api/v1/settings", json={"cancellation_cutoff_hours": 24}, headers=boss
        ).status_code
        == 200
    )
    assert client.get("/api/v1/settings").json()["cancellation_cutoff_hours"] == 24

    move_clock_to(frozen_clock, START - timedelta(hours=23))  # inside the new 24 h cutoff
    late = client.post(f"{BASE}/{booking_id}/cancel", headers=headers(ali_user, frozen_clock))

    assert late.status_code == 409
    assert late.json()["error"]["details"]["cutoff_at"].startswith("2026-10-04T05:00:00")


def test_admin_cancelling_a_confirmed_booking_needs_a_reason(client, setup, ali, boss):
    booking_id = book(client, setup, ali)
    client.post(f"{BASE}/{booking_id}/confirm", headers=boss)

    missing = client.post(f"{BASE}/{booking_id}/cancel", headers=boss)
    assert missing.status_code == 422
    assert error_code(missing) == "REASON_REQUIRED"

    ok = client.post(f"{BASE}/{booking_id}/cancel", json={"reason": "Barber sick"}, headers=boss)
    assert ok.status_code == 200
    assert ok.json()["cancel_reason"] == "Barber sick"


def test_a_cancelled_booking_cannot_be_cancelled_again(client, setup, ali):
    booking_id = book(client, setup, ali)
    client.post(f"{BASE}/{booking_id}/cancel", headers=ali)

    response = client.post(f"{BASE}/{booking_id}/cancel", headers=ali)

    assert response.status_code == 409
    assert error_code(response) == "INVALID_TRANSITION"


# --- complete -------------------------------------------------------------


def test_admin_completes_only_after_the_booking_ends(client, setup, ali, boss_user, frozen_clock):
    booking_id = book(client, setup, ali)
    client.post(f"{BASE}/{booking_id}/confirm", headers=headers(boss_user, frozen_clock))

    early = client.post(f"{BASE}/{booking_id}/complete", headers=headers(boss_user, frozen_clock))
    assert early.status_code == 409
    assert error_code(early) == "TOO_EARLY_TO_COMPLETE"

    move_clock_to(frozen_clock, START + timedelta(minutes=30))
    done = client.post(f"{BASE}/{booking_id}/complete", headers=headers(boss_user, frozen_clock))
    assert done.status_code == 200
    assert done.json()["status"] == "completed"


# --- auth -----------------------------------------------------------------


def test_anonymous_is_401_on_every_transition(client):
    for action in ("cancel", "confirm", "complete"):
        assert client.post(f"{BASE}/1/{action}").status_code == 401
    assert client.get(f"{BASE}/all").status_code == 401


# --- admin list -----------------------------------------------------------


def test_admin_list_needs_admin(client, ali):
    response = client.get(f"{BASE}/all", headers=ali)
    assert response.status_code == 403
    assert error_code(response) == "FORBIDDEN"


def test_admin_list_shows_everyones_bookings_soonest_first(client, setup, ali, bob, boss):
    late = book(client, setup, bob, ELEVEN)
    early = book(client, setup, ali, TEN)

    page = client.get(f"{BASE}/all", headers=boss).json()

    assert page["total"] == 2
    assert [b["id"] for b in page["items"]] == [early, late]


def test_admin_list_filters(client, db, setup, ali_user, bob, boss, frozen_clock):
    _, provider = setup
    other_provider = Provider(name="Aziz")
    db.add(other_provider)
    db.flush()
    ali = headers(ali_user, frozen_clock)
    first = book(client, setup, ali, TEN)
    second = book(client, setup, bob, ELEVEN)
    client.post(f"{BASE}/{second}/confirm", headers=boss)
    next_week = book(client, setup, ali, "2026-10-12T05:00:00Z")

    def ids(query: str) -> list[int]:
        response = client.get(f"{BASE}/all?{query}", headers=boss)
        assert response.status_code == 200, response.text
        return [b["id"] for b in response.json()["items"]]

    assert ids("status=confirmed") == [second]
    assert ids(f"customer_id={ali_user.id}") == [first, next_week]
    assert ids(f"provider_id={provider.id}") == [first, second, next_week]
    assert ids(f"provider_id={other_provider.id}") == []
    # Local days: both Oct 5 bookings start that day in Tashkent, Oct 12 is a week later.
    assert ids("date_from=2026-10-05&date_to=2026-10-05") == [first, second]
    assert ids("date_from=2026-10-06") == [next_week]
    assert ids("date_to=2026-10-11") == [first, second]


def test_admin_list_date_filter_uses_the_business_timezone(client, setup, ali, boss):
    # 05:00 UTC is 10:00 on Oct 5 in Tashkent: it is on the 5th, not the 4th.
    booking_id = book(client, setup, ali, TEN)

    on_5th = client.get(f"{BASE}/all?date_from=2026-10-05&date_to=2026-10-05", headers=boss)
    on_4th = client.get(f"{BASE}/all?date_to=2026-10-04", headers=boss)

    assert [b["id"] for b in on_5th.json()["items"]] == [booking_id]
    assert on_4th.json()["total"] == 0


def test_admin_list_is_paginated(client, setup, ali, bob, boss):
    book(client, setup, ali, TEN)
    book(client, setup, bob, ELEVEN)

    page = client.get(f"{BASE}/all?limit=1&offset=1", headers=boss).json()

    assert page["total"] == 2
    assert len(page["items"]) == 1


def test_my_list_is_still_only_my_own_for_an_admin(client, setup, ali, boss):
    book(client, setup, ali)
    assert client.get(BASE, headers=boss).json()["total"] == 0


# --- history --------------------------------------------------------------


def test_history_lists_create_confirm_cancel_in_order(client, setup, ali, boss, ali_user):
    booking_id = book(client, setup, ali)
    client.post(f"{BASE}/{booking_id}/confirm", headers=boss)
    client.post(f"{BASE}/{booking_id}/cancel", json={"reason": "Ill"}, headers=ali)

    response = client.get(f"{BASE}/{booking_id}/history", headers=ali)

    assert response.status_code == 200
    events = response.json()
    assert [(e["from_status"], e["to_status"]) for e in events] == [
        (None, "pending"),
        ("pending", "confirmed"),
        ("confirmed", "cancelled"),
    ]
    assert events[0]["actor"] == {"id": ali_user.id, "role": "customer", "name": "ali@example.com"}
    assert events[1]["actor"]["role"] == "admin"
    assert events[2]["reason"] == "Ill"
    assert events[0]["reason"] is None


def test_admin_can_read_any_history(client, setup, ali, boss):
    booking_id = book(client, setup, ali)
    assert len(client.get(f"{BASE}/{booking_id}/history", headers=boss).json()) == 1


def test_history_of_someone_elses_booking_is_404(client, setup, ali, bob):
    booking_id = book(client, setup, ali)

    for who in (bob, ali):
        missing = booking_id + 1000 if who is ali else booking_id
        response = client.get(f"{BASE}/{missing}/history", headers=who)
        assert response.status_code == 404
        assert error_code(response) == "BOOKING_NOT_FOUND"


def test_history_needs_login(client):
    assert client.get(f"{BASE}/1/history").status_code == 401
