"""A barber's phone number: what is accepted, and the one shape it is stored in."""

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.provider import ProviderUpdate
from app.schemas.types import PhoneNumber

PHONE = TypeAdapter(PhoneNumber)


@pytest.mark.parametrize(
    "typed",
    [
        "+998901234567",
        "+998 90 123 45 67",
        "+998 (90) 123-45-67",
        "+998.90.123.45.67",
        "+998 90 123 45 67",  # copied from a page, no-break spaces
    ],
)
def test_the_usual_spellings_are_stored_as_e164(typed):
    assert PHONE.validate_python(typed) == "+998901234567"


@pytest.mark.parametrize(
    "typed",
    [
        "901234567",  # no country code: a different number in every country
        "8 901 234 56 78",
        "+",
        "+0998901234567",  # a country code never starts with 0
        "+998 90 ABC 45 67",
        "+١٢٣٤٥٦٧٨٩",  # Arabic-Indic digits are digits to Python, not to a phone
        "+1234567",  # 7 digits: too short
        "+1234567890123456",  # 16 digits: longer than E.164 allows
    ],
)
def test_anything_else_is_refused(typed):
    with pytest.raises(ValidationError):
        PHONE.validate_python(typed)


def test_the_shortest_and_longest_lengths_are_allowed():
    assert PHONE.validate_python("+12345678") == "+12345678"
    assert PHONE.validate_python("+123456789012345") == "+123456789012345"


@pytest.mark.parametrize("blank", ["", "   "])
def test_an_empty_phone_field_clears_the_number(blank):
    assert ProviderUpdate(phone=blank).phone is None
