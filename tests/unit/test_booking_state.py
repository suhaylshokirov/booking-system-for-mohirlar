"""Every allowed and forbidden (from, to, role) combination, and the time boundaries."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import product

import pytest

from app.core.errors import AppError
from app.models.booking import BookingStatus as S
from app.models.user import UserRole
from app.services.booking_state import (
    ALLOWED,
    CancellationCutoffPassed,
    ReasonRequired,
    TooEarlyToComplete,
    can_cancel,
    check_transition,
    is_stale_pending,
)

START = datetime(2026, 10, 6, 10, 0, tzinfo=UTC)
END = START + timedelta(minutes=30)
BEFORE = START - timedelta(days=1)  # well before start and before the cutoff
CUTOFF = START - timedelta(hours=2)


@dataclass
class Booking:
    status: S
    customer_id: int = 1
    provider_id: int = 7
    start_at: datetime = START
    end_at: datetime = END


@dataclass
class Actor:
    id: int
    role: UserRole
    provider_id: int | None = None


@dataclass
class Settings:
    cancellation_cutoff_hours: int = 2


OWNER = Actor(1, UserRole.CUSTOMER)
STRANGER = Actor(2, UserRole.CUSTOMER)
# The barber the booking was made with (provider 7), and a different barber (provider 8).
BARBER = Actor(99, UserRole.BARBER, provider_id=7)
OTHER_BARBER = Actor(98, UserRole.BARBER, provider_id=8)


def check(frm, to, actor, now=BEFORE, reason="because"):
    return check_transition(Booking(frm), to, actor, now, Settings(), reason)


def error_code(*args, **kwargs) -> str:
    with pytest.raises(AppError) as exc:
        check(*args, **kwargs)
    return exc.value.code


@pytest.mark.parametrize(
    ("frm", "to", "actor"),
    [
        (S.PENDING, S.CONFIRMED, BARBER),
        (S.PENDING, S.CANCELLED, OWNER),
        (S.PENDING, S.CANCELLED, BARBER),
        (S.CONFIRMED, S.CANCELLED, OWNER),
        (S.CONFIRMED, S.CANCELLED, BARBER),
    ],
)
def test_allowed_transitions(frm, to, actor):
    check(frm, to, actor)


def test_barber_completes_a_confirmed_booking_after_it_ends():
    check(S.CONFIRMED, S.COMPLETED, BARBER, now=END)


@pytest.mark.parametrize(
    ("frm", "to"), [p for p in product(S, S) if p not in ALLOWED], ids=lambda s: s.value
)
@pytest.mark.parametrize("actor", [OWNER, BARBER], ids=["owner", "barber"])
def test_every_pair_not_in_the_table_is_invalid(frm, to, actor):
    assert error_code(frm, to, actor, now=END) == "INVALID_TRANSITION"


@pytest.mark.parametrize("frm", [S.CANCELLED, S.COMPLETED])
def test_terminal_statuses_go_nowhere(frm):
    for to in S:
        assert error_code(frm, to, BARBER, now=END) == "INVALID_TRANSITION"


@pytest.mark.parametrize(("frm", "to"), [(a, b) for a, b in ALLOWED if b != S.CANCELLED], ids=str)
@pytest.mark.parametrize("actor", [OWNER, STRANGER], ids=["owner", "stranger"])
def test_customers_cannot_confirm_or_complete(frm, to, actor):
    assert error_code(frm, to, actor, now=END) == "INVALID_TRANSITION"


@pytest.mark.parametrize("frm", [S.PENDING, S.CONFIRMED])
def test_a_customer_cannot_cancel_someone_elses_booking(frm):
    assert error_code(frm, S.CANCELLED, STRANGER) == "INVALID_TRANSITION"


def test_confirm_needs_a_future_start():
    check(S.PENDING, S.CONFIRMED, BARBER, now=START - timedelta(seconds=1))
    assert error_code(S.PENDING, S.CONFIRMED, BARBER, now=START) == "INVALID_TRANSITION"


def test_customer_cancels_confirmed_exactly_at_the_cutoff():
    check(S.CONFIRMED, S.CANCELLED, OWNER, now=CUTOFF)


def test_customer_cannot_cancel_confirmed_after_the_cutoff():
    with pytest.raises(CancellationCutoffPassed) as exc:
        check(S.CONFIRMED, S.CANCELLED, OWNER, now=CUTOFF + timedelta(seconds=1))
    assert exc.value.status_code == 409
    assert exc.value.details == {"cutoff_at": CUTOFF.isoformat()}


def test_customer_cancels_pending_until_it_starts():
    check(S.PENDING, S.CANCELLED, OWNER, now=START - timedelta(seconds=1))
    assert error_code(S.PENDING, S.CANCELLED, OWNER, now=START) == "CANCELLATION_CUTOFF_PASSED"


def test_barber_is_exempt_from_the_cutoff_but_needs_a_reason():
    late = CUTOFF + timedelta(minutes=30)
    check(S.CONFIRMED, S.CANCELLED, BARBER, now=late)
    for reason in (None, "", "   "):
        with pytest.raises(ReasonRequired) as exc:
            check(S.CONFIRMED, S.CANCELLED, BARBER, now=late, reason=reason)
        assert exc.value.status_code == 422


def test_barber_cancelling_pending_needs_no_reason_even_after_start():
    check(S.PENDING, S.CANCELLED, BARBER, now=END, reason=None)


def test_barber_cannot_cancel_a_confirmed_booking_that_has_started():
    assert error_code(S.CONFIRMED, S.CANCELLED, BARBER, now=START) == "INVALID_TRANSITION"


def test_cannot_complete_before_end_at():
    with pytest.raises(TooEarlyToComplete) as exc:
        check(S.CONFIRMED, S.COMPLETED, BARBER, now=END - timedelta(seconds=1))
    assert exc.value.details == {"end_at": END.isoformat()}


def test_stale_pending_means_pending_and_started():
    assert not is_stale_pending(Booking(S.PENDING), START - timedelta(seconds=1))
    assert is_stale_pending(Booking(S.PENDING), START)
    assert not is_stale_pending(Booking(S.CONFIRMED), END)
    assert not is_stale_pending(Booking(S.CANCELLED), END)


# --- can_cancel: the Cancel button asks the same rule the server enforces ------------


@pytest.mark.parametrize(
    ("status", "now", "expected"),
    [
        (S.PENDING, START - timedelta(minutes=1), True),  # no cutoff for a pending booking
        (S.PENDING, START, False),
        (S.CONFIRMED, CUTOFF, True),  # inclusive, like check_transition
        (S.CONFIRMED, CUTOFF + timedelta(seconds=1), False),
        (S.CANCELLED, BEFORE, False),
        (S.COMPLETED, BEFORE, False),
    ],
)
def test_can_cancel_follows_check_transition_for_the_owner(status, now, expected):
    assert can_cancel(Booking(status), OWNER, now, Settings()) is expected


def test_can_cancel_is_false_for_a_stranger():
    assert can_cancel(Booking(S.PENDING), STRANGER, BEFORE, Settings()) is False


def test_the_bookings_barber_can_cancel_a_confirmed_booking_without_a_reason_being_a_no():
    # The reason is asked for at cancel time; it must not hide the button.
    assert can_cancel(Booking(S.CONFIRMED), BARBER, BEFORE, Settings()) is True


@pytest.mark.parametrize(
    ("frm", "to"), [(S.PENDING, S.CONFIRMED), (S.PENDING, S.CANCELLED), (S.CONFIRMED, S.COMPLETED)]
)
def test_another_barber_has_no_say_in_the_booking(frm, to):
    now = END if to == S.COMPLETED else BEFORE
    assert error_code(frm, to, OTHER_BARBER, now=now) == "INVALID_TRANSITION"


def test_a_barber_who_is_the_customer_may_cancel_as_a_customer_not_as_the_barber():
    # A barber who booked someone else's chair is just a customer there: the
    # cutoff applies to them, and they cannot confirm.
    booking_barber_is_customer = Actor(1, UserRole.BARBER, provider_id=8)
    assert error_code(S.PENDING, S.CONFIRMED, booking_barber_is_customer) == "INVALID_TRANSITION"
    check(S.PENDING, S.CANCELLED, booking_barber_is_customer)
