"""The booking page's own small pieces: the slot value and day parts."""

from datetime import UTC, datetime

import pytest

from app.core.errors import AppError
from app.models.provider import Provider
from app.services.slot_query import ProviderSlots
from app.web.booking import day_parts, parse_provider_filter, parse_slot, slot_value

TEN_LOCAL = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)  # 10:00 in Tashkent (UTC+5)


def test_a_slot_value_round_trips():
    assert parse_slot(slot_value(7, TEN_LOCAL)) == (7, TEN_LOCAL)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "7",
        "x|2026-10-02T05:00:00+00:00",
        "7|tomorrow",
        "7|2026-10-02T05:00:00",  # no offset: which clock would that be?
    ],
)
def test_anything_else_is_invalid_slot(value):
    with pytest.raises(AppError) as caught:
        parse_slot(value)
    assert caught.value.code == "INVALID_SLOT"


@pytest.mark.parametrize(("value", "expected"), [(None, None), ("", None), ("any", None), ("3", 3)])
def test_provider_filter(value, expected):
    assert parse_provider_filter(value) == expected


def test_a_non_number_provider_filter_is_rejected():
    with pytest.raises(AppError) as caught:
        parse_provider_filter("jasur")
    assert caught.value.code == "INVALID_PROVIDER"


def test_day_parts_split_on_the_local_clock_and_skip_empty_parts():
    def at(hour: int, minute: int = 0) -> datetime:  # local Tashkent hour -> UTC
        return datetime(2026, 10, 2, hour - 5, minute, tzinfo=UTC)

    starts = [at(9), at(11, 45), at(12), at(16, 45), at(19)]
    grouped = day_parts(ProviderSlots(Provider(id=1, name="Jasur"), starts), "Asia/Tashkent")

    assert [(label, [c.start for c in choices]) for label, choices in grouped.parts] == [
        ("Morning", [at(9), at(11, 45)]),
        ("Afternoon", [at(12), at(16, 45)]),
        ("Evening", [at(19)]),
    ]
    assert grouped.count == 5
    assert grouped.parts[0][1][0].value == slot_value(1, at(9))


def test_a_day_with_only_an_afternoon_has_only_that_part():
    one = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)  # 14:00 local
    grouped = day_parts(ProviderSlots(Provider(id=1, name="Jasur"), [one]), "Asia/Tashkent")

    assert [label for label, _ in grouped.parts] == ["Afternoon"]
