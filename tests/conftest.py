"""Shared fixtures: a real PostgreSQL, isolated per test.

Two ways to get a database session:

* `db` (used by `client` too): the default. Everything a test does is rolled
  back afterwards, so tests are fast and cannot affect each other.
* `committing_db`: for concurrency tests, where several threads need separate
  connections and real commits. It truncates every table afterwards instead.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.deps import get_login_limiter
from app.core.clock import FrozenClock, get_clock
from app.core.config import get_settings
from app.core.db import get_db
from app.core.mail import get_mailer
from app.core.rate_limit import InMemoryLoginLimiter
from app.core.security import create_access_token
from app.main import create_app
from app.models.provider import Provider
from app.models.user import User, UserRole
from tests.support import (
    Mailbox,
    build_schema,
    ensure_test_database_is_separate,
    truncate_all_tables,
)


def pytest_configure(config: pytest.Config) -> None:
    # Checked before anything runs, so even a unit-only run cannot get past a
    # misconfigured environment.
    try:
        ensure_test_database_is_separate(get_settings())
    except RuntimeError as error:
        raise pytest.UsageError(str(error)) from error


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    """Engine on the test database, with the schema built once per test run."""
    test_engine = create_engine(get_settings().test_database_url, pool_pre_ping=True)
    build_schema(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    """A session whose work is rolled back when the test ends.

    The session runs inside an outer transaction that is never committed.
    `create_savepoint` turns the session's own `commit()` into a savepoint
    release, so code under test can commit freely and the data still vanishes.
    """
    connection = engine.connect()
    outer_transaction = connection.begin()
    session = Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    yield session
    session.close()
    outer_transaction.rollback()
    connection.close()


@pytest.fixture
def committing_db(engine: Engine) -> Iterator[sessionmaker[Session]]:
    """A session factory whose sessions really commit; tables are emptied after.

    Only for tests that need real commits from several connections at once
    (the race-condition tests). Each thread opens its own session from it.
    """
    yield sessionmaker(bind=engine, expire_on_commit=False)
    truncate_all_tables(engine)


@pytest.fixture
def frozen_clock() -> FrozenClock:
    """Time stands still at Thursday 2026-10-01 07:00 UTC (12:00 in Tashkent)."""
    return FrozenClock(datetime(2026, 10, 1, 7, 0, tzinfo=UTC))


@pytest.fixture
def mailbox() -> Mailbox:
    """Where the emails the app sends end up; read sign-in codes from it."""
    return Mailbox()


@pytest.fixture
def client(db: Session, frozen_clock: FrozenClock, mailbox: Mailbox) -> Iterator[TestClient]:
    """API client wired to the rolled-back `db` session, the frozen clock and the `mailbox`."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clock] = lambda: frozen_clock
    app.dependency_overrides[get_mailer] = lambda: mailbox
    # A fresh limiter per test: the real one is process-wide, so failed logins
    # in one test would otherwise count against the next.
    limiter = InMemoryLoginLimiter(max_attempts=5, window_seconds=300)
    app.dependency_overrides[get_login_limiter] = lambda: limiter
    with TestClient(app) as test_client:
        yield test_client


class AuthHeaders(dict):
    """Request headers that authenticate as `user`; for a barber, also their `provider`."""

    user: User
    provider: Provider | None = None


def _auth_headers(db: Session, clock: FrozenClock, role: UserRole) -> AuthHeaders:
    """Bearer headers for a new user of `role` (Bearer needs no CSRF token).

    A barber comes with the provider record they log in as: the database
    requires one (`ck_users_barber_has_provider`).
    """
    provider = None
    if role == UserRole.BARBER:
        provider = Provider(name="Barber")
        db.add(provider)
        db.flush()
    user = User(
        email=f"{role.value}@example.com",
        full_name="Test User",
        role=role,
        provider_id=provider.id if provider else None,
    )
    db.add(user)
    db.flush()
    headers = AuthHeaders(Authorization=f"Bearer {create_access_token(user.id, clock.now())}")
    headers.user, headers.provider = user, provider
    return headers


@pytest.fixture
def barber(db: Session, frozen_clock: FrozenClock) -> AuthHeaders:
    """Request headers that authenticate as a barber; `.provider` is the one they run."""
    return _auth_headers(db, frozen_clock, UserRole.BARBER)


@pytest.fixture
def customer(db: Session, frozen_clock: FrozenClock) -> AuthHeaders:
    """Request headers that authenticate as a customer."""
    return _auth_headers(db, frozen_clock, UserRole.CUSTOMER)
