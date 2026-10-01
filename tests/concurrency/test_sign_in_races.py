"""Race conditions around sign-in codes, with real commits and threads (P12.2).

A code must work once even if two requests carry it at the same moment, and a
sign-up code must create one account, not two. A barrier placed after each
request has matched the code forces both to have read it as live before either
claims it, so only the database (the guarded `UPDATE ... WHERE consumed_at IS
NULL`) can stop the second one. (The unique index on `lower(email)` is a second
line of defence; `test_auth.py` forces it by hiding the account from the first lookup.)

Frozen clock: 2026-10-01 07:00 UTC.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.deps import get_login_limiter
from app.core.mail import get_mailer
from app.core.rate_limit import InMemoryLoginLimiter
from app.core.security import hash_login_code
from app.models import LoginCode, User
from app.services import auth as auth_service
from tests.support import Mailbox

VERIFY = "/api/v1/auth/verify"
EMAIL = "aziza@example.com"


@pytest.fixture
def sign_in_app(app):
    app.dependency_overrides[get_mailer] = lambda: Mailbox()
    roomy = InMemoryLoginLimiter(max_attempts=100, window_seconds=300)
    app.dependency_overrides[get_login_limiter] = lambda: roomy
    return app


def _both_have_matched(monkeypatch, parties: int = 2):
    """Make every verification wait, after matching its code, for the others to match."""
    barrier = threading.Barrier(parties)
    real = auth_service.login_code_matches

    def match_then_wait(*args, **kwargs):
        result = real(*args, **kwargs)
        barrier.wait(timeout=10)
        return result

    monkeypatch.setattr(auth_service, "login_code_matches", match_then_wait)


def _verify_together(app, codes):
    def send(code):
        with TestClient(app) as client:
            return client.post(VERIFY, json={"email": EMAIL, "code": code})

    with ThreadPoolExecutor(max_workers=len(codes)) as pool:
        return list(pool.map(send, codes))


def _insert_code(committing_db, clock, code, full_name=None):
    with committing_db() as db:
        db.add(
            LoginCode(
                email=EMAIL,
                code_hash=hash_login_code(EMAIL, code),
                full_name=full_name,
                created_at=clock.now(),
                expires_at=clock.now() + auth_service.CODE_LIFETIME,
            )
        )
        db.commit()


def test_one_code_used_by_two_requests_at_once_signs_in_exactly_one(
    sign_in_app, committing_db, frozen_clock, monkeypatch
):
    with committing_db() as db:
        db.add(User(email=EMAIL, full_name="Aziza"))
        db.commit()
    _insert_code(committing_db, frozen_clock, "123456")
    _both_have_matched(monkeypatch)

    first, second = _verify_together(sign_in_app, ["123456", "123456"])

    assert sorted([first.status_code, second.status_code]) == [200, 401]
    loser = first if first.status_code == 401 else second
    assert loser.json()["error"]["code"] == "INVALID_CODE"
    with committing_db() as db:
        [row] = db.scalars(select(LoginCode)).all()
        assert row.consumed_at is not None


def test_one_sign_up_code_used_twice_at_once_creates_exactly_one_account(
    sign_in_app, committing_db, frozen_clock, monkeypatch
):
    """Nobody has an account yet: both requests see a live sign-up code and would create
    the customer. The guarded claim lets one through, so there is one account and one winner."""
    _insert_code(committing_db, frozen_clock, "123456", full_name="Aziza")
    _both_have_matched(monkeypatch)

    first, second = _verify_together(sign_in_app, ["123456", "123456"])

    assert sorted([first.status_code, second.status_code]) == [200, 401]
    with committing_db() as db:
        assert db.scalar(select(func.count(User.id)).where(User.email == EMAIL)) == 1
