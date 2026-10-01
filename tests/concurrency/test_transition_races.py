"""Race conditions on booking status changes, with real commits and threads (P7.6).

Barber confirm and customer cancel start from the same `pending` booking. The
guarded `UPDATE ... WHERE status = :expected` (ADR 0008) must let exactly one
win. A barrier placed *after* each request's rules check forces both to have
read `pending` before either writes, so only the guard can stop the second one.

Frozen clock: 2026-10-01 07:00 UTC; the booking is 2026-10-05 05:00 UTC.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.security import create_access_token
from app.models import Booking, BookingEvent, BookingStatus, User, UserRole
from app.services import booking as booking_service

START = "2026-10-05T05:00:00Z"
BASE = "/api/v1/bookings"


def make_barber(committing_db, clock, provider_id: int) -> dict[str, str]:
    """The barber who runs `provider_id`: only they may act on its bookings."""
    with committing_db() as db:
        user = User(
            email="boss@example.com",
            password_hash="x",
            full_name="Boss",
            role=UserRole.BARBER,
            provider_id=provider_id,
        )
        db.add(user)
        db.commit()
        return {"Authorization": f"Bearer {create_access_token(user.id, clock.now())}"}


def create_pending(app, world, headers, start=START) -> int:
    with TestClient(app) as client:
        response = client.post(
            BASE,
            json={
                "service_id": world["service_id"],
                "provider_id": world["provider_ids"][0],
                "start_at": start,
            },
            headers=headers,
        )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def fire_together(app, calls):
    """Run each (path, headers, json) POST in its own thread, released together."""
    barrier = threading.Barrier(len(calls))

    def send(call):
        path, headers, json = call
        with TestClient(app) as client:
            barrier.wait(timeout=10)
            return client.post(path, headers=headers, json=json)

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return list(pool.map(send, calls))


def history(committing_db, booking_id):
    with committing_db() as db:
        events = db.scalars(
            select(BookingEvent)
            .where(BookingEvent.booking_id == booking_id)
            .order_by(BookingEvent.id)
        ).all()
        status = db.get(Booking, booking_id).status
        return status, [(e.from_status, e.to_status) for e in events]


def test_concurrent_confirm_and_cancel_exactly_one_wins(
    app, world, committing_db, frozen_clock, monkeypatch
):
    customer = world["customer"](1)
    barber = make_barber(committing_db, frozen_clock, world["provider_ids"][0])
    booking_id = create_pending(app, world, customer)

    # Both requests finish the rules check on `pending` before either writes.
    both_have_read = threading.Barrier(2)
    real_check = booking_service.check_transition

    def check_then_wait(*args, **kwargs):
        real_check(*args, **kwargs)
        both_have_read.wait(timeout=10)

    monkeypatch.setattr(booking_service, "check_transition", check_then_wait)

    confirm, cancel = fire_together(
        app,
        [
            (f"{BASE}/{booking_id}/confirm", barber, None),
            (f"{BASE}/{booking_id}/cancel", customer, {"reason": "Changed my mind"}),
        ],
    )

    assert sorted([confirm.status_code, cancel.status_code]) == [200, 409]
    loser = confirm if confirm.status_code == 409 else cancel
    assert loser.json()["error"]["code"] == "BOOKING_STATE_CHANGED"

    status, events = history(committing_db, booking_id)
    winner_status = (
        BookingStatus.CONFIRMED if confirm.status_code == 200 else BookingStatus.CANCELLED
    )
    assert status == winner_status
    # The creation event plus exactly one transition: the loser wrote nothing.
    assert events == [(None, BookingStatus.PENDING), (BookingStatus.PENDING, winner_status)]


def test_unforced_confirm_and_cancel_never_leave_history_and_status_disagreeing(
    app, world, committing_db, frozen_clock
):
    """No forced interleaving: either order is legal (confirm then cancel is allowed),
    but whatever happens, the last event must be the booking's status."""
    barber = make_barber(committing_db, frozen_clock, world["provider_ids"][0])
    for n in range(6):
        customer = world["customer"](n + 10)
        # One booking per round, on its own 30-minute slot, for a different customer.
        start = f"2026-10-05T0{4 + n // 2}:{'00' if n % 2 == 0 else '30'}:00Z"
        booking_id = create_pending(app, world, customer, start)

        confirm, cancel = fire_together(
            app,
            [
                (f"{BASE}/{booking_id}/confirm", barber, None),
                (f"{BASE}/{booking_id}/cancel", customer, None),
            ],
        )

        assert {confirm.status_code, cancel.status_code} <= {200, 409}
        assert 200 in (confirm.status_code, cancel.status_code)
        status, events = history(committing_db, booking_id)
        assert events[-1][1] == status
        successes = [r for r in (confirm, cancel) if r.status_code == 200]
        assert len(events) == 1 + len(successes)


def test_a_cancelled_slot_is_immediately_bookable_by_another_customer(app, world):
    first = world["customer"](1)
    second = world["customer"](2)
    booking_id = create_pending(app, world, first)

    with TestClient(app) as client:
        assert client.post(f"{BASE}/{booking_id}/cancel", headers=first).status_code == 200
        again = client.post(
            BASE,
            json={
                "service_id": world["service_id"],
                "provider_id": world["provider_ids"][0],
                "start_at": START,
            },
            headers=second,
        )

    assert again.status_code == 201
