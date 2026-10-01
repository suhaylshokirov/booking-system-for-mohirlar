"""Availability edits never touch bookings; the barber is told what no longer fits (P4.4).

The frozen clock is 2026-10-01 07:00 UTC. 2026-10-05 is a Monday; Tashkent is
UTC+5, so 09:00 local is 04:00 UTC.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AvailabilityException,
    AvailabilityRule,
    Booking,
    BookingStatus,
    Provider,
    Service,
    User,
)

MONDAY_UTC = datetime(2026, 10, 5, tzinfo=UTC)  # midnight UTC; Tashkent is +5


def _provider(db: Session, name="Jasur") -> Provider:
    provider = Provider(name=name)
    db.add(provider)
    db.flush()
    return provider


def _rule(db, provider, weekday=0, start=(9, 0), end=(18, 0)) -> AvailabilityRule:
    rule = AvailabilityRule(
        provider_id=provider.id, weekday=weekday, start_time=time(*start), end_time=time(*end)
    )
    db.add(rule)
    db.flush()
    return rule


def _exception(db, provider, day, start=None, end=None) -> AvailabilityException:
    row = AvailabilityException(provider_id=provider.id, date=day, start_time=start, end_time=end)
    db.add(row)
    db.flush()
    return row


def _booking(
    db, provider, start_utc, minutes=30, status=BookingStatus.CONFIRMED, customer=None
) -> Booking:
    if customer is None:
        customer = db.scalar(select(User).where(User.email == "guest@example.com"))
    if customer is None:
        customer = User(email="guest@example.com", full_name="Guest")
        db.add(customer)
    service = db.scalar(select(Service))
    if service is None:
        service = Service(name="Haircut", duration_minutes=30, price=60000)
        db.add(service)
    db.flush()
    booking = Booking(
        customer_id=customer.id,
        provider_id=provider.id,
        service_id=service.id,
        start_at=start_utc,
        end_at=start_utc + timedelta(minutes=minutes),
        status=status,
        price_amount=60000,
        duration_minutes=minutes,
    )
    db.add(booking)
    db.flush()
    return booking


def _local(hour: int, minute=0, day=5) -> datetime:
    """A Tashkent wall-clock time on 2026-10-<day> as a UTC instant."""
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC) - timedelta(hours=5)


def _base(provider: Provider, suffix: str) -> str:
    return f"/api/v1/providers/{provider.id}/availability/{suffix}"


def _conflict_ids(response) -> list[int]:
    return [c["booking_id"] for c in response.json()["details"]["conflicts"]]


# --- the conflicts endpoint --------------------------------------------------


def test_a_booking_inside_the_hours_is_not_a_conflict(client, barber, db):
    provider = barber.provider
    _rule(db, provider)
    _booking(db, provider, _local(10))

    assert client.get(_base(provider, "conflicts"), headers=barber).json() == []


def test_a_booking_touching_the_window_edges_still_fits(client, barber, db):
    """Half-open ranges: 09:00-09:30 and 17:30-18:00 are inside 09:00-18:00."""
    provider = barber.provider
    _rule(db, provider)
    _booking(db, provider, _local(9))
    _booking(db, provider, _local(17, 30))

    assert client.get(_base(provider, "conflicts"), headers=barber).json() == []


def test_a_booking_running_past_closing_is_outside_hours(client, barber, db):
    provider = barber.provider
    _rule(db, provider)
    late = _booking(db, provider, _local(17, 45))  # ends 18:15

    body = client.get(_base(provider, "conflicts"), headers=barber).json()

    assert [(c["booking_id"], c["reason"]) for c in body] == [(late.id, "outside_hours")]
    assert body[0]["status"] == "confirmed"


def test_a_booking_on_a_weekday_without_rules_is_no_hours(client, barber, db):
    provider = barber.provider
    _rule(db, provider, weekday=1)  # Tuesday only
    monday = _booking(db, provider, _local(10))

    body = client.get(_base(provider, "conflicts"), headers=barber).json()

    assert [(c["booking_id"], c["reason"]) for c in body] == [(monday.id, "no_hours")]


def test_a_day_off_exception_is_reported_as_day_off(client, barber, db):
    provider = barber.provider
    _rule(db, provider)
    _exception(db, provider, date(2026, 10, 5))
    booking = _booking(db, provider, _local(10))

    body = client.get(_base(provider, "conflicts"), headers=barber).json()

    assert [(c["booking_id"], c["reason"]) for c in body] == [(booking.id, "day_off")]


def test_custom_hours_replace_the_weekly_rules(client, barber, db):
    provider = barber.provider
    _rule(db, provider)  # Monday 09-18
    _exception(db, provider, date(2026, 10, 5), time(12), time(16))
    morning = _booking(db, provider, _local(10))  # inside the rule, outside the exception
    afternoon = _booking(db, provider, _local(13))  # inside the exception

    body = client.get(_base(provider, "conflicts"), headers=barber).json()

    assert [c["booking_id"] for c in body] == [morning.id]
    assert afternoon.id not in [c["booking_id"] for c in body]


def test_a_booking_is_judged_on_its_local_date_not_its_utc_date(client, barber, db):
    """01:00 Monday in Tashkent is 20:00 Sunday UTC: the Monday rule does not cover it."""
    provider = barber.provider
    _rule(db, provider, weekday=0)
    night = _booking(db, provider, datetime(2026, 10, 4, 20, 0, tzinfo=UTC))

    body = client.get(_base(provider, "conflicts"), headers=barber).json()

    assert [(c["booking_id"], c["reason"]) for c in body] == [(night.id, "outside_hours")]


def test_only_future_active_bookings_of_this_provider_count(client, barber, db):
    jasur, aziz = barber.provider, _provider(db, "Aziz")
    nothing_open = _local(10)
    for status in (BookingStatus.CANCELLED, BookingStatus.COMPLETED):
        _booking(db, jasur, nothing_open, status=status)
    _booking(db, aziz, nothing_open)  # someone else's
    _booking(db, jasur, datetime(2026, 10, 1, 6, 0, tzinfo=UTC))  # already started
    pending = _booking(db, jasur, _local(11), status=BookingStatus.PENDING)

    body = client.get(_base(jasur, "conflicts"), headers=barber).json()

    assert [(c["booking_id"], c["status"]) for c in body] == [(pending.id, "pending")]


def test_conflicts_are_listed_earliest_first(client, barber, db):
    provider = barber.provider
    later = _booking(db, provider, _local(15))
    sooner = _booking(db, provider, _local(10))

    body = client.get(_base(provider, "conflicts"), headers=barber).json()

    assert [c["booking_id"] for c in body] == [sooner.id, later.id]


def test_conflicts_endpoint_is_for_the_barber_themselves_and_403_for_another_provider(
    client, barber, customer, db
):
    provider = barber.provider
    assert client.get(_base(provider, "conflicts")).status_code == 401
    assert client.get(_base(provider, "conflicts"), headers=customer).status_code == 403
    # Another provider's id, or none at all, is not the barber's own: 403.
    assert (
        client.get("/api/v1/providers/999/availability/conflicts", headers=barber).status_code
        == 403
    )


# --- warnings on write responses ---------------------------------------------


def test_removing_a_rule_under_a_booking_warns_and_keeps_the_booking(client, barber, db):
    provider = barber.provider
    rule = _rule(db, provider)
    booking = _booking(db, provider, _local(10))

    response = client.delete(_base(provider, f"rules/{rule.id}"), headers=barber)

    assert response.status_code == 200
    assert response.json()["id"] == rule.id
    assert _conflict_ids(response) == [booking.id]
    assert db.get(AvailabilityRule, rule.id) is None
    db.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED
    listed = client.get(_base(provider, "conflicts"), headers=barber).json()
    assert [c["booking_id"] for c in listed] == [booking.id]


def test_narrowing_a_rule_warns_about_the_bookings_it_cuts_off(client, barber, db):
    provider = barber.provider
    rule = _rule(db, provider)
    kept = _booking(db, provider, _local(10))
    cut = _booking(db, provider, _local(16))

    response = client.patch(
        _base(provider, f"rules/{rule.id}"), json={"end_time": "12:00"}, headers=barber
    )

    assert response.status_code == 200
    assert response.json()["end_time"] == "12:00:00"  # the change itself is applied
    assert _conflict_ids(response) == [cut.id]
    assert kept.id not in _conflict_ids(response)


def test_a_harmless_change_returns_an_empty_warning(client, barber, db):
    provider = barber.provider
    _rule(db, provider, weekday=1)  # Tuesday
    response = client.post(
        _base(provider, "rules"),
        json={"weekday": 2, "start_time": "09:00", "end_time": "18:00"},
        headers=barber,
    )
    assert response.status_code == 201
    assert response.json()["details"] == {"conflicts": []}


def test_adding_a_rule_can_clear_an_existing_conflict(client, barber, db):
    provider = barber.provider
    _booking(db, provider, _local(10))  # no rules yet: a conflict

    response = client.post(
        _base(provider, "rules"),
        json={"weekday": 0, "start_time": "09:00", "end_time": "18:00"},
        headers=barber,
    )

    assert response.json()["details"]["conflicts"] == []


def test_a_day_off_over_a_booking_warns_and_keeps_it(client, barber, db):
    provider = barber.provider
    _rule(db, provider)
    booking = _booking(db, provider, _local(10))

    response = client.post(
        _base(provider, "exceptions"), json={"date": "2026-10-05"}, headers=barber
    )

    assert response.status_code == 201
    assert response.json()["is_day_off"] is True
    assert [(c["booking_id"], c["reason"]) for c in response.json()["details"]["conflicts"]] == [
        (booking.id, "day_off")
    ]
    db.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED


def test_editing_an_exception_updates_the_warning(client, barber, db):
    provider = barber.provider
    _rule(db, provider)
    row = _exception(db, provider, date(2026, 10, 5))
    booking = _booking(db, provider, _local(10))

    reopened = client.patch(
        _base(provider, f"exceptions/{row.id}"),
        json={"start_time": "09:00", "end_time": "18:00"},
        headers=barber,
    )

    assert reopened.status_code == 200
    assert _conflict_ids(reopened) == []
    db.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED


def test_deleting_an_exception_reports_what_the_rules_do_not_cover(client, barber, db):
    provider = barber.provider
    row = _exception(db, provider, date(2026, 10, 5), time(9), time(18))
    booking = _booking(db, provider, _local(10))  # no weekly rule at all

    response = client.delete(_base(provider, f"exceptions/{row.id}"), headers=barber)

    assert response.status_code == 200
    assert _conflict_ids(response) == [booking.id]


@pytest.mark.parametrize("suffix", ["rules", "exceptions"])
def test_a_rejected_change_returns_an_error_not_a_warning(client, barber, db, suffix):
    provider = barber.provider
    body = (
        {"weekday": 0, "start_time": "09:10", "end_time": "18:00"}
        if suffix == "rules"
        else {"date": "2020-01-01"}
    )
    response = client.post(_base(provider, suffix), json=body, headers=barber)
    assert response.status_code == 422
    assert "conflicts" not in str(response.json()["error"]["details"])
