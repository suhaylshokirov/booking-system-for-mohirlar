"""GET /api/v1/health against a real PostgreSQL (the shared `client` fixture)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.main import create_app


@pytest.fixture
def client_with_dead_database() -> Iterator[TestClient]:
    # Port 1 refuses connections immediately, standing in for a database that is down.
    engine = create_engine(
        "postgresql+psycopg://navbat:navbat@localhost:1/navbat?connect_timeout=2"
    )

    def override_get_db() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    engine.dispose()


def test_health_is_ok_when_database_answers(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_is_503_database_unavailable_when_database_is_down(client_with_dead_database):
    response = client_with_dead_database.get("/api/v1/health")

    assert response.status_code == 503
    error = response.json()["error"]
    assert error["code"] == "DATABASE_UNAVAILABLE"
    assert set(error) == {"code", "message", "details"}
