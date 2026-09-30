"""Race conditions on POST /bookings, with real commits and real threads (P6.4).

Every request runs in its own thread with its own database session and its own
committed transaction, and a `Barrier` releases them together. This is the proof
that double booking is impossible: the service's overlap pre-check alone cannot
give it (two requests can both see the slot free), so what stops the losers is
the Postgres exclusion constraint (ADR 0001).

Frozen clock: 2026-10-01 07:00 UTC. Monday 2026-10-05, 10:00 Tashkent = 05:00 UTC.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.clock import get_clock
from app.core.db import get_db
from app.core.security import create_access_token, hash_password
from app.main import create_app
from app.models import AvailabilityRule, Booking, Provider, ProviderService, Service, User
from app.services import booking as booking_service
from app.services.business_settings import get_business_settings

START = "2026-10-05T05:00:00Z"
OVERLAPPING = "2026-10-05T05:15:00Z"


@pytest.fixture
def world(committing_db, frozen_clock):
    """Committed data: one service, two providers who offer it, and a factory for customers."""
    with committing_db() as db:
        # Commit the settings row up front. `get_business_settings` creates it on
        # first use, and a second transaction's insert would wait for the first to
        # commit, which the forced-interleaving barriers below would turn into a
        # deadlock that has nothing to do with bookings.
        get_business_settings(db)
        service = Service(name="Haircut", duration_minutes=30, price=60000)
        providers = [Provider(name="Jasur"), Provider(name="Aziz")]
        db.add(service)
        db.add_all(providers)
        db.flush()
        for provider in providers:
            db.add(ProviderService(provider_id=provider.id, service_id=service.id))
            db.add(
                AvailabilityRule(
                    provider_id=provider.id, weekday=0, start_time=time(9), end_time=time(12)
                )
            )
        db.commit()
        service_id, provider_ids = service.id, [p.id for p in providers]

    def new_customer(n: int) -> dict[str, str]:
        with committing_db() as db:
            user = User(
                email=f"customer{n}@example.com",
                password_hash=hash_password("x"),
                full_name=f"Customer {n}",
            )
            db.add(user)
            db.commit()
            return {"Authorization": f"Bearer {create_access_token(user.id, frozen_clock.now())}"}

    return {"service_id": service_id, "provider_ids": provider_ids, "customer": new_customer}


@pytest.fixture
def app(committing_db, frozen_clock):
    app = create_app()

    def real_commit_session():
        # Same contract as the production `get_db`: commit on success, roll back on error.
        with committing_db() as db:
            yield db
            db.commit()

    app.dependency_overrides[get_db] = real_commit_session
    app.dependency_overrides[get_clock] = lambda: frozen_clock
    return app


def fire_together(app, requests):
    """Send each (headers, json) in its own thread, all released at the same instant.

    Returns the responses in the same order as `requests`.
    """
    barrier = threading.Barrier(len(requests))

    def send(request):
        headers, body = request
        with TestClient(app) as client:
            barrier.wait(timeout=10)
            return client.post("/api/v1/bookings", json=body, headers=headers)

    with ThreadPoolExecutor(max_workers=len(requests)) as pool:
        return list(pool.map(send, requests))


def body(world, provider_index=0, start=START):
    return {
        "service_id": world["service_id"],
        "provider_id": world["provider_ids"][provider_index],
        "start_at": start,
    }


def count_bookings(committing_db) -> int:
    with committing_db() as db:
        return db.scalar(select(func.count()).select_from(Booking))


def error_codes(responses) -> list[str]:
    return [r.json()["error"]["code"] for r in responses if r.status_code != 201]


def test_n_customers_same_slot_exactly_one_wins(app, world, committing_db):
    requests = [(world["customer"](n), body(world)) for n in range(10)]

    responses = fire_together(app, requests)

    assert sorted(r.status_code for r in responses) == [201] + [409] * 9
    assert error_codes(responses) == ["SLOT_TAKEN"] * 9
    assert count_bookings(committing_db) == 1


def test_all_pass_the_precheck_and_the_constraint_still_stops_them(
    app, world, committing_db, monkeypatch
):
    """Forces the worst interleaving instead of hoping for it.

    Every thread finishes the overlap pre-check (all see a free slot) before any
    of them inserts. A Python-only check would let all ten through; the
    exclusion constraint must reject nine, and the error must still be the
    friendly `SLOT_TAKEN`.
    """
    everyone_checked = threading.Barrier(10)
    real_precheck = booking_service._precheck_overlap

    def precheck_then_wait(*args):
        real_precheck(*args)
        everyone_checked.wait(timeout=10)

    monkeypatch.setattr(booking_service, "_precheck_overlap", precheck_then_wait)
    requests = [(world["customer"](n), body(world)) for n in range(10)]

    responses = fire_together(app, requests)

    assert sorted(r.status_code for r in responses) == [201] + [409] * 9
    assert error_codes(responses) == ["SLOT_TAKEN"] * 9
    assert count_bookings(committing_db) == 1


def test_overlapping_but_not_identical_starts_still_allow_only_one(app, world, committing_db):
    """10:00 and 10:15 overlap; the constraint compares ranges, not equal start times."""
    requests = [
        (world["customer"](0), body(world, start=START)),
        (world["customer"](1), body(world, start=OVERLAPPING)),
    ]

    responses = fire_together(app, requests)

    assert sorted(r.status_code for r in responses) == [201, 409]
    assert count_bookings(committing_db) == 1


def test_same_customer_two_providers_overlapping_one_rejected(
    app, world, committing_db, monkeypatch
):
    """One person cannot be in two chairs at once, even with different providers."""
    both_checked = threading.Barrier(2)
    real_precheck = booking_service._precheck_overlap

    def precheck_then_wait(*args):
        real_precheck(*args)
        both_checked.wait(timeout=10)

    monkeypatch.setattr(booking_service, "_precheck_overlap", precheck_then_wait)
    ali = world["customer"](0)
    requests = [
        (ali, body(world, provider_index=0, start=START)),
        (ali, body(world, provider_index=1, start=OVERLAPPING)),
    ]

    responses = fire_together(app, requests)

    assert sorted(r.status_code for r in responses) == [201, 409]
    assert error_codes(responses) == ["CUSTOMER_OVERLAP"]
    assert count_bookings(committing_db) == 1


def test_double_submit_same_request_creates_one_booking(app, world, committing_db):
    """A double-clicked button sends the identical request twice at once."""
    ali = world["customer"](0)

    responses = fire_together(app, [(ali, body(world)), (ali, body(world))])

    assert sorted(r.status_code for r in responses) == [201, 409]
    # The loser broke both constraints (same provider, same customer); either
    # code is a true answer, and the client just has to see a 409.
    assert error_codes(responses)[0] in {"SLOT_TAKEN", "CUSTOMER_OVERLAP"}
    assert count_bookings(committing_db) == 1


def test_different_slots_at_the_same_moment_all_succeed(app, world, committing_db):
    """The constraint must not serialise unrelated bookings: no false conflicts."""
    starts = [
        "2026-10-05T05:00:00Z",
        "2026-10-05T05:30:00Z",
        "2026-10-05T06:00:00Z",
        "2026-10-05T06:30:00Z",
    ]
    requests = [(world["customer"](n), body(world, start=s)) for n, s in enumerate(starts)]

    responses = fire_together(app, requests)

    assert [r.status_code for r in responses] == [201] * 4
    assert count_bookings(committing_db) == 4
