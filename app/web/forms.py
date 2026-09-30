"""Turning a Pydantic validation error into messages a person can act on.

Web forms validate with the same schemas as the API (`app/schemas/`), so a
rule exists once. Only the wording differs: Pydantic says "String should have
at least 8 characters"; the form says "Use at least 8 characters."
"""

from pydantic import ValidationError


def field_errors(error: ValidationError, messages: dict[str, str]) -> dict[str, str]:
    """The first problem per field, in the form's own words.

    `messages` is keyed `"field.error_type"` for a specific case (for example
    `"password.string_too_short"`) or `"field"` for any problem with it. A
    field with neither falls back to Pydantic's own message.
    """
    errors: dict[str, str] = {}
    for problem in error.errors():
        field = str(problem["loc"][0]) if problem["loc"] else ""
        message = messages.get(f"{field}.{problem['type']}") or messages.get(field)
        errors.setdefault(field, message or problem["msg"])
    return errors
