"""GET /api/v1/health against a real PostgreSQL.

These fixtures are deliberately minimal; P0.5 replaces them with the shared
harness (migrated schema, per-test rollback).
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.main import create_app


def _client_using(database_url: str) -> Iterator[TestClient]:
    engine = create_engine(database_url)

    def override_get_db() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as client:
        yield client
    engine.dispose()


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from _client_using(get_settings().test_database_url)


@pytest.fixture
def client_with_dead_database() -> Iterator[TestClient]:
    # Port 1 refuses connections immediately, standing in for a database that is down.
    yield from _client_using(
        "postgresql+psycopg://navbat:navbat@localhost:1/navbat?connect_timeout=2"
    )


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
