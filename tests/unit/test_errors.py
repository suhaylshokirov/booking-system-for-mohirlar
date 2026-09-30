"""Every kind of error under /api/, ours and the framework's, renders the one envelope.

The probe routes live under /api/ because paths outside it are web pages and
get an HTML error page instead (tests/integration/test_web_foundation.py).
"""

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from app.core.errors import AppError
from app.main import create_app


class _Payload(BaseModel):
    name: str = Field(min_length=1)


@pytest.fixture
def client() -> TestClient:
    app = create_app()

    @app.get("/api/test/boom-app-error")
    def boom_app_error():
        raise AppError(
            "SLOT_TAKEN",
            "That time was just booked by someone else.",
            status_code=409,
            details={"slot": "10:00"},
            headers={"Retry-After": "5"},
        )

    @app.post("/api/test/needs-body")
    def needs_body(payload: _Payload):
        return {"name": payload.name}

    @app.get("/api/test/boom-unexpected")
    def boom_unexpected():
        raise RuntimeError("secret internal detail: password=hunter2")

    # raise_server_exceptions=False so the 500 handler's response is observable
    # instead of the exception being re-raised into the test.
    return TestClient(app, raise_server_exceptions=False)


def _assert_envelope(response, status: int, code: str) -> dict:
    assert response.status_code == status
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code
    return body["error"]


def test_app_error_uses_its_own_code_status_details_and_headers(client):
    response = client.get("/api/test/boom-app-error")

    error = _assert_envelope(response, 409, "SLOT_TAKEN")
    assert error["message"] == "That time was just booked by someone else."
    assert error["details"] == {"slot": "10:00"}
    assert response.headers["retry-after"] == "5"


def test_validation_error_is_422_with_field_level_details(client):
    response = client.post("/api/test/needs-body", json={"name": ""})

    error = _assert_envelope(response, 422, "VALIDATION_ERROR")
    problem = error["details"]["errors"][0]
    assert problem["field"] == "body.name"
    assert problem["type"] == "string_too_short"


def test_malformed_json_is_422_in_the_same_envelope(client):
    response = client.post(
        "/api/test/needs-body", content="{not json", headers={"Content-Type": "application/json"}
    )

    _assert_envelope(response, 422, "VALIDATION_ERROR")


def test_unknown_route_is_404_envelope(client):
    _assert_envelope(client.get("/api/v1/nope"), 404, "NOT_FOUND")


def test_wrong_method_is_405_envelope_and_keeps_allow_header(client):
    response = client.post("/api/v1/health")

    _assert_envelope(response, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in response.headers["allow"]


def test_unexpected_exception_is_500_and_does_not_leak_internals(client):
    response = client.get("/api/test/boom-unexpected")

    error = _assert_envelope(response, 500, "INTERNAL_ERROR")
    assert "hunter2" not in response.text
    assert error["details"] == {}
