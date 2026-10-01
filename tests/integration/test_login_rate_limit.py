"""Wrong sign-in codes are rate limited per (client IP, email) (P2.5, reworked in P12.2).

The limiter counts wrong guesses at `POST /auth/verify`, never requests for a code
(those have their own per-address limit, tested in test_auth.py).
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_login_limiter
from app.core.clock import FrozenClock, get_clock
from app.core.db import get_db
from app.core.mail import get_mailer
from app.core.rate_limit import InMemoryLoginLimiter
from app.main import create_app
from app.models.user import User
from tests.support import Mailbox

LOGIN = "/api/v1/auth/login"
VERIFY = "/api/v1/auth/verify"
EMAIL = "aziza@example.com"
ATTEMPTS = 5  # the `client` fixture's limiter allows 5 failures per 300 s


@pytest.fixture(autouse=True)
def _account(db: Session):
    db.add(User(email=EMAIL, full_name="Aziza"))
    db.add(User(email="other@example.com", full_name="Other"))
    db.flush()


@pytest.fixture
def code(client, mailbox):
    """The right code for EMAIL, requested fresh."""
    client.post(LOGIN, json={"email": EMAIL})
    return mailbox.last_code(EMAIL)


def _verify(client, code, email=EMAIL):
    return client.post(VERIFY, json={"email": email, "code": code})


def _wrong(code):
    return "000000" if code != "000000" else "111111"


def _fail(client, times, code="000000", email=EMAIL):
    # Each wrong guess also uses one of the code's own five tries, so five wrong
    # guesses reach the IP limit and kill the code together.
    for _ in range(times):
        assert _verify(client, code, email).status_code == 401


def test_the_attempt_after_the_limit_is_429_with_retry_after(client, code):
    _fail(client, ATTEMPTS, _wrong(code))

    response = _verify(client, _wrong(code))

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "TOO_MANY_ATTEMPTS"
    assert response.headers["Retry-After"] == "300"
    assert response.json()["error"]["details"] == {"retry_after_seconds": 300}


def test_even_the_correct_code_is_refused_while_blocked(client, code):
    """Otherwise the limit would only slow guessing down, not stop it."""
    _fail(client, ATTEMPTS, _wrong(code))

    assert _verify(client, code).status_code == 429


def test_the_wait_shrinks_as_time_passes(client, frozen_clock, code):
    _fail(client, ATTEMPTS, _wrong(code))
    frozen_clock.advance(timedelta(seconds=100))

    assert _verify(client, code).headers["Retry-After"] == "200"


def test_access_returns_when_the_window_expires(client, mailbox, frozen_clock, code):
    _fail(client, ATTEMPTS, _wrong(code))
    frozen_clock.advance(timedelta(seconds=299))
    assert _verify(client, code).status_code == 429

    frozen_clock.advance(timedelta(seconds=1))

    # No longer blocked. (This code is still dead: five wrong tries also use up
    # a code's own allowance, so the person asks for a new one.)
    assert _verify(client, code).json()["error"]["code"] == "INVALID_CODE"
    client.post(LOGIN, json={"email": EMAIL})
    assert _verify(client, mailbox.last_code(EMAIL)).status_code == 200


def test_blocked_attempts_do_not_extend_the_block(client, frozen_clock, code):
    _fail(client, ATTEMPTS, _wrong(code))
    for _ in range(10):
        assert _verify(client, code).status_code == 429
        frozen_clock.advance(timedelta(seconds=29))

    # 290 s in: the block still ends at 300 s after the failures, not later.
    assert _verify(client, code).headers["Retry-After"] == "10"


def test_a_successful_sign_in_clears_the_counter(client, mailbox, code):
    _fail(client, ATTEMPTS - 2, _wrong(code))
    assert _verify(client, code).status_code == 200
    client.cookies.clear()
    client.post(LOGIN, json={"email": EMAIL})
    fresh = mailbox.last_code(EMAIL)

    _fail(client, ATTEMPTS - 1, _wrong(fresh))  # would be a 429 if the earlier failures counted
    assert _verify(client, fresh).status_code == 200


def test_below_the_limit_failures_are_still_plain_401s(client, code):
    _fail(client, ATTEMPTS - 1, _wrong(code))


def test_other_emails_are_unaffected(client, mailbox, code):
    _fail(client, ATTEMPTS, _wrong(code))
    client.post(LOGIN, json={"email": "other@example.com"})

    assert (
        _verify(client, mailbox.last_code("other@example.com"), "other@example.com").status_code
        == 200
    )


def test_email_case_and_padding_share_one_counter(client, code):
    for variant in [
        "aziza@example.com",
        "AZIZA@example.com",
        " Aziza@Example.com ",
        "aziza@EXAMPLE.com",
        "azIza@example.com",
    ]:
        assert _verify(client, _wrong(code), variant).status_code == 401

    assert _verify(client, code, "aziza@example.com").status_code == 429


def test_unknown_emails_are_limited_the_same_way(client):
    """Or the 429 itself would reveal which emails have accounts."""
    ghost = "nobody@example.com"
    _fail(client, ATTEMPTS, "123456", email=ghost)

    assert _verify(client, "123456", ghost).status_code == 429


def test_a_different_client_ip_is_not_blocked(client, mailbox, code):
    """Someone failing against your address cannot lock *you* out from elsewhere.

    Their five wrong tries do use up that code (a code's tries are per code), so you
    ask for a new one; but your IP is not on their counter.
    """
    with TestClient(client.app, client=("198.51.100.9", 50000)) as attacker:
        _fail(attacker, ATTEMPTS, _wrong(code))
        assert _verify(attacker, code).status_code == 429

    client.post(LOGIN, json={"email": EMAIL})

    assert _verify(client, mailbox.last_code(EMAIL)).status_code == 200


def test_malformed_requests_do_not_count(client, code):
    for _ in range(ATTEMPTS + 3):
        assert _verify(client, "12ab").status_code == 422

    assert _verify(client, code).status_code == 200


def test_the_limits_come_from_settings(
    db: Session, frozen_clock: FrozenClock, mailbox: Mailbox, monkeypatch
):
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
        app.dependency_overrides[get_mailer] = lambda: mailbox
        with TestClient(app) as strict:
            strict.post(LOGIN, json={"email": EMAIL})
            right = mailbox.last_code(EMAIL)
            assert _verify(strict, _wrong(right)).status_code == 401
            assert _verify(strict, _wrong(right)).status_code == 401
            blocked = _verify(strict, right)
            assert blocked.status_code == 429
            assert blocked.headers["Retry-After"] == "60"
    finally:
        get_login_limiter.cache_clear()
