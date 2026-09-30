"""How a booking's history reads to the customer who owns it."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.models.booking import BookingStatus as S
from app.web.my_bookings import describe_event

AT = datetime(2026, 10, 1, 7, 0, tzinfo=UTC)
ME = SimpleNamespace(id=1)
STAFF = SimpleNamespace(id=99)


def event(to, reason=None):
    return SimpleNamespace(to_status=to, created_at=AT, reason=reason)


@pytest.mark.parametrize(
    ("to", "actor", "text"),
    [
        (S.PENDING, ME, "Requested by you"),
        (S.CONFIRMED, STAFF, "Confirmed by the business"),
        (S.COMPLETED, STAFF, "Marked as completed"),
        (S.CANCELLED, ME, "Cancelled by you"),
        (S.CANCELLED, STAFF, "Cancelled by the business"),
        (S.CANCELLED, None, "Cancelled"),
    ],
)
def test_each_event_reads_as_a_sentence(to, actor, text):
    assert describe_event(event(to), actor, ME).text == text


def test_the_reason_and_time_are_carried_over():
    entry = describe_event(event(S.CANCELLED, "not confirmed in time"), None, ME)

    assert entry.reason == "not confirmed in time"
    assert entry.at == AT
