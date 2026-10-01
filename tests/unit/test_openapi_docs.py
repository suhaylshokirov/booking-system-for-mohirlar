"""The API documentation is complete and honest (P10.4). No database.

Swagger is generated from the routes, so these tests read the generated OpenAPI
document and fail when a new endpoint is added without its documentation.
"""

import re
from pathlib import Path

import pytest

from app.core.error_catalog import ERROR_CATALOG
from app.main import create_app

ROOT = Path(__file__).resolve().parent.parent.parent
SPEC = create_app().openapi()
SCHEMAS = SPEC["components"]["schemas"]
OPERATIONS = [
    (method.upper(), path, op) for path, ops in SPEC["paths"].items() for method, op in ops.items()
]
IDS = [f"{m} {p}" for m, p, _ in OPERATIONS]

# Public reads that take no input cannot fail except unexpectedly (the 500 every
# operation documents), so they have no 4xx to list.
CANNOT_FAIL_BY_INPUT = {"GET /api/v1/settings"}


def _error_codes(responses: dict) -> list[int]:
    return sorted(int(c) for c in responses if c.isdigit() and int(c) >= 400 and c != "500")


def _schema_of(content: dict) -> dict:
    schema = content["application/json"]["schema"]
    if schema.get("type") == "array":
        schema = schema["items"]
    if "anyOf" in schema:
        schema = next(s for s in schema["anyOf"] if "$ref" in s)
    if "$ref" in schema:
        return SCHEMAS[schema["$ref"].split("/")[-1]]
    return schema


def test_every_operation_is_found():
    assert len(OPERATIONS) >= 38


@pytest.mark.parametrize(("method", "path", "op"), OPERATIONS, ids=IDS)
def test_has_a_summary_a_description_and_a_tag(method, path, op):
    assert op.get("summary"), "give the route a summary="
    assert (op.get("description") or "").strip(), "give the function a docstring"
    assert op.get("tags"), "give the router a tag"


@pytest.mark.parametrize(("method", "path", "op"), OPERATIONS, ids=IDS)
def test_documents_at_least_one_error_response(method, path, op):
    if f"{method} {path}" in CANNOT_FAIL_BY_INPUT:
        pytest.skip("cannot fail by input")
    assert _error_codes(op["responses"]), "add responses= with the errors it can return"


@pytest.mark.parametrize(("method", "path", "op"), OPERATIONS, ids=IDS)
def test_every_error_response_uses_the_envelope_and_shows_an_example(method, path, op):
    for status, response in op["responses"].items():
        if not (status.isdigit() and int(status) >= 400):
            continue
        content = response["content"]["application/json"]
        assert content["schema"]["$ref"].endswith("/ErrorResponse"), (
            f"{status} must be documented as the error envelope, not FastAPI's default"
        )
        error = content["example"]["error"]
        assert set(error) == {"code", "message", "details"}
        assert error["code"] in ERROR_CATALOG, f"{error['code']} is not in the error catalog"
        assert ERROR_CATALOG[error["code"]][0] in (int(status), 422, 401, 403), (error, status)


@pytest.mark.parametrize(("method", "path", "op"), OPERATIONS, ids=IDS)
def test_request_bodies_and_success_responses_have_examples(method, path, op):
    body = op.get("requestBody")
    if body and "multipart/form-data" in body["content"]:
        # A file upload has no JSON example to show; each field must say what it takes.
        ref = body["content"]["multipart/form-data"]["schema"]["$ref"]
        for name, field in SCHEMAS[ref.split("/")[-1]]["properties"].items():
            assert field.get("description"), f"describe the {name} upload field"
    elif body:
        schema = _schema_of(body["content"])
        assert schema.get("examples") or schema.get("example"), "add an example to the schema"
    for status, response in op["responses"].items():
        if status.startswith("2") and "content" in response:
            content = response["content"]
            if "application/json" not in content:
                continue  # the .ics download is text/calendar
            has_media_example = "example" in content["application/json"]
            schema = _schema_of(content)
            assert has_media_example or schema.get("examples") or schema.get("example"), (
                f"{status} response has no example"
            )


@pytest.mark.parametrize(("method", "path", "op"), OPERATIONS, ids=IDS)
def test_every_parameter_is_described(method, path, op):
    for parameter in op.get("parameters", []):
        assert parameter.get("description"), f"describe the {parameter['name']} parameter"


def test_the_framework_validation_error_shape_is_not_advertised():
    """FastAPI documents a 422 as {"detail": [...]}; this API sends the envelope."""
    assert "HTTPValidationError" not in SCHEMAS
    assert "ValidationError" not in SCHEMAS


# --- the error code table ---------------------------------------------------------------


def _doc_table() -> dict[str, tuple[int, str]]:
    text = (ROOT / "docs" / "api.md").read_text()
    section = text[text.index("## Error codes") : text.index("## Health check")]
    rows = re.findall(r"^\| `([A-Z_]+)` \| (\d+) \| (.*) \|$", section, re.M)
    return {code: (int(status), meaning) for code, status, meaning in rows}


def test_the_docs_error_table_is_exactly_the_catalog():
    assert _doc_table() == ERROR_CATALOG


def test_every_code_the_app_can_raise_is_in_the_catalog():
    raised = set()
    pattern = re.compile(
        r"(?:AppError|_invalid|InvalidTokenError|error_response|super\(\)\.__init__)\(\s*"
        r"(?:\d+,\s*)?\"([A-Z][A-Z_]+)\""
    )
    for path in (ROOT / "app").rglob("*.py"):
        raised.update(pattern.findall(path.read_text()))
    assert raised, "the scan found nothing; the pattern is wrong"
    assert raised <= set(ERROR_CATALOG), sorted(raised - set(ERROR_CATALOG))


def test_every_code_named_in_a_description_is_in_the_catalog():
    named = set()
    for _method, _path, op in OPERATIONS:
        for response in op["responses"].values():
            named.update(re.findall(r"`([A-Z][A-Z_]{3,})`", response.get("description", "")))
    # Words that are backticked but are not error codes (HTTP-ish or config names).
    named -= {"GET", "POST", "PUT", "PATCH", "DELETE"}
    assert named <= set(ERROR_CATALOG), sorted(named - set(ERROR_CATALOG))
