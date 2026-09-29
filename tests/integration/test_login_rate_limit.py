"""POST /auth/login is rate limited per (client IP, email) (P2.5)."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_login_limiter
from app.core.clock import FrozenClock, get_clock
from app.core.db import get_db
from app.core.rate_limit import InMemoryLoginLimiter
from app.main import create_app
from app.models.user import User

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
PASSWORD = "a long passphrase"
EMAIL = "aziza@example.com"
ATTEMPTS = 5  # the `client` fixture's limiter allows 5 failures per 300 s


@pytest.fixture(autouse=True)
def _account(client):
    client.post(REGISTER, json={"email": EMAIL, "password": PASSWORD, "full_name": "Aziza"})


def _login(client, email=EMAIL, password=PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


def _fail(client, times, email=EMAIL):
    for _ in range(times):
        assert _login(client, email, "wrong password").status_code == 401


def test_the_attempt_after_the_limit_is_429_with_retry_after(client):
    _fail(client, ATTEMPTS)

    response = _login(client, password="wrong password")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert response.headers["Retry-After"] == "300"
    assert response.json()["error"]["details"] == {"retry_after_seconds": 300}


def test_even_the_correct_password_is_refused_while_blocked(client):
    """Otherwise the limit would only slow guessing down, not stop it."""
    _fail(client, ATTEMPTS)

    assert _login(client).status_code == 429


def test_the_wait_shrinks_as_time_passes(client, frozen_clock):
    _fail(client, ATTEMPTS)
    frozen_clock.advance(timedelta(seconds=100))

    assert _login(client).headers["Retry-After"] == "200"


def test_access_returns_when_the_window_expires(client, frozen_clock):
    _fail(client, ATTEMPTS)
    frozen_clock.advance(timedelta(seconds=299))
    assert _login(client).status_code == 429

    frozen_clock.advance(timedelta(seconds=1))

    assert _login(client).status_code == 200


def test_blocked_attempts_do_not_extend_the_block(client, frozen_clock):
    _fail(client, ATTEMPTS)
    for _ in range(10):
        assert _login(client).status_code == 429
        frozen_clock.advance(timedelta(seconds=29))

    # 290 s in: the block still ends at 300 s after the failures, not later.
    assert _login(client).headers["Retry-After"] == "10"


def test_a_successful_login_clears_the_counter(client):
    _fail(client, ATTEMPTS - 1)
    assert _login(client).status_code == 200
    client.cookies.clear()

    _fail(client, ATTEMPTS - 1)  # would be a 429 if the earlier failures still counted
    assert _login(client).status_code == 200


def test_below_the_limit_failures_are_still_plain_401s(client):
    _fail(client, ATTEMPTS)  # asserts every one is a 401


def test_other_emails_are_unaffected(client):
    _fail(client, ATTEMPTS)
    other = "other@example.com"
    client.post(REGISTER, json={"email": other, "password": PASSWORD, "full_name": "O"})

    assert _login(client, other).status_code == 200


def test_email_case_and_padding_share_one_counter(client):
    for variant in [
        "aziza@example.com",
        "AZIZA@example.com",
        " Aziza@Example.com ",
        "aziza@EXAMPLE.com",
        "azIza@example.com",
    ]:
        assert _login(client, variant, "wrong password").status_code == 401

    assert _login(client, "aziza@example.com").status_code == 429


def test_unknown_emails_are_limited_the_same_way(client):
    """Or the 429 itself would reveal which emails have accounts."""
    ghost = "nobody@example.com"
    _fail(client, ATTEMPTS, email=ghost)

    assert _login(client, ghost).status_code == 429


def test_a_different_client_ip_is_not_blocked(client):
    """Someone failing against your address cannot lock *you* out from elsewhere."""
    _fail(client, ATTEMPTS)
    assert _login(client).status_code == 429

    app = client.app
    with TestClient(app, client=("198.51.100.9", 50000)) as elsewhere:
        assert _login(elsewhere).status_code == 200


def test_a_deactivated_account_is_not_counted_as_guessing(client, db: Session):
    db.query(User).update({"is_active": False})
    db.flush()

    for _ in range(ATTEMPTS + 3):
        response = _login(client)  # right password every time
        assert (response.status_code, response.json()["error"]["code"]) == (401, "ACCOUNT_INACTIVE")


def test_malformed_requests_do_not_count(client):
    for _ in range(ATTEMPTS + 3):
        assert client.post(LOGIN, json={"email": EMAIL}).status_code == 422

    assert _login(client).status_code == 200


def test_the_limits_come_from_settings(db: Session, frozen_clock: FrozenClock, monkeypatch):
    """`get_login_limiter` builds the limiter from the two env-configurable values."""
    from app.core.config import Settings

    monkeypatch.setattr(
        "app.api.deps.get_settings",
        lambda: Settings(login_rate_limit_attempts=2, login_rate_limit_window_seconds=60),
    )
    get_login_limiter.cache_clear()
    try:
        limiter = get_login_limiter()
        assert isinstance(limiter, InMemoryLoginLimiter)
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_clock] = lambda: frozen_clock
        with TestClient(app) as strict:
            strict.post(REGISTER, json={"email": EMAIL, "password": PASSWORD, "full_name": "A"})
            assert _login(strict, password="wrong password").status_code == 401
            assert _login(strict, password="wrong password").status_code == 401
            blocked = _login(strict)
            assert blocked.status_code == 429
            assert blocked.headers["Retry-After"] == "60"
    finally:
        get_login_limiter.cache_clear()
