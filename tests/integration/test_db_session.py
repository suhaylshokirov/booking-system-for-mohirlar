"""The per-request transaction policy of `get_db` / `DbSession`.

These tests use real commits (`committing_db`) because the policy is about
what reaches the database, which a rolled-back test session would hide.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core import db as db_module
from app.core.db import DbSession, get_db
from app.core.errors import AppError, register_error_handlers


@pytest.fixture(scope="module", autouse=True)
def probe_table(engine):
    """`deferred_probe` rejects duplicate values, but only when the transaction
    commits, which lets a test make the commit itself fail."""
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE session_probe (note text NOT NULL)"))
        connection.execute(
            text(
                "CREATE TABLE deferred_probe (n int NOT NULL, "
                "CONSTRAINT deferred_probe_n_key UNIQUE (n) DEFERRABLE INITIALLY DEFERRED)"
            )
        )
    yield
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE session_probe, deferred_probe"))


@pytest.fixture(autouse=True)
def use_test_database(committing_db, monkeypatch):
    """Point `get_db` at the test database instead of DATABASE_URL."""
    monkeypatch.setattr(db_module, "SessionLocal", committing_db)


def _count(engine, table: str) -> int:
    # A separate connection: it only sees what was really committed.
    with engine.connect() as connection:
        return connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def _probe_app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.post("/write", status_code=201)
    def write(db: DbSession) -> dict:
        db.execute(text("INSERT INTO session_probe VALUES ('ok')"))
        return {"saved": True}

    @app.post("/write-then-fail")
    def write_then_fail(db: DbSession) -> dict:
        db.execute(text("INSERT INTO session_probe VALUES ('half done')"))
        raise AppError("SLOT_TAKEN", "Taken.", status_code=409)

    @app.post("/commit-fails", status_code=201)
    def commit_fails(db: DbSession) -> dict:
        # Two equal values pass at INSERT time and only violate the constraint
        # when the transaction commits, i.e. after this handler has returned.
        db.execute(text("INSERT INTO deferred_probe VALUES (1), (1)"))
        return {"saved": True}

    return app


def test_commits_when_the_handler_returns(engine):
    dependency = get_db()
    session = next(dependency)
    session.execute(text("INSERT INTO session_probe VALUES ('kept')"))

    with pytest.raises(StopIteration):
        next(dependency)  # the handler finished normally

    assert _count(engine, "session_probe") == 1


def test_rolls_back_and_reraises_when_the_handler_raises(engine):
    dependency = get_db()
    session = next(dependency)
    session.execute(text("INSERT INTO session_probe VALUES ('discarded')"))

    with pytest.raises(RuntimeError, match="boom"):
        dependency.throw(RuntimeError("boom"))

    assert _count(engine, "session_probe") == 0


def test_request_that_returns_normally_is_saved(engine):
    response = TestClient(_probe_app()).post("/write")

    assert response.status_code == 201
    assert _count(engine, "session_probe") == 1


def test_request_that_raises_an_app_error_writes_nothing(engine):
    response = TestClient(_probe_app()).post("/write-then-fail")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "SLOT_TAKEN"
    assert _count(engine, "session_probe") == 0


def test_failed_commit_is_an_error_not_a_success_response(engine):
    """The commit runs before the response is sent (`scope="function"`).

    With the default scope the client would already hold "201 saved" when the
    commit fails. Here it gets the 500 envelope, and nothing was stored.
    """
    client = TestClient(_probe_app(), raise_server_exceptions=False)

    response = client.post("/commit-fails")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert _count(engine, "deferred_probe") == 0
