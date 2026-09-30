"""`field_errors`: schema errors in the form's own words."""

from pydantic import ValidationError

from app.schemas.auth import RegisterRequest
from app.web.forms import field_errors


def _error(**data) -> ValidationError:
    try:
        RegisterRequest(**data)
    except ValidationError as error:
        return error
    raise AssertionError("expected the input to be invalid")


def test_a_specific_message_beats_the_fields_general_one():
    error = _error(email="a@example.com", password="short", full_name="Aziza")

    messages = {"password.string_too_short": "Use at least 8.", "password": "Bad password."}

    assert field_errors(error, messages) == {"password": "Use at least 8."}


def test_the_general_message_covers_any_problem_with_the_field():
    error = _error(email="not-an-email", password="a long passphrase", full_name="Aziza")

    assert field_errors(error, {"email": "Enter an email."}) == {"email": "Enter an email."}


def test_a_field_without_wording_falls_back_to_pydantics_message():
    error = _error(email="a@example.com", password="a long passphrase", full_name="")

    assert "at least 1 character" in field_errors(error, {})["full_name"]


def test_every_invalid_field_gets_one_message():
    error = _error(email="x", password="short", full_name="")

    assert set(field_errors(error, {})) == {"email", "password", "full_name"}
