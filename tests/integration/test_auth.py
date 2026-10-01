"""/auth: sign up and in with an emailed code, log out, /me; against a real PostgreSQL.

Time is the frozen clock; the code is read from the `mailbox` fixture, the way a
person reads it from their inbox.
"""

from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.rate_limit import InMemoryLoginLimiter
from app.core.security import hash_login_code
from app.models.login_code import LoginCode
from app.models.user import User, UserRole
from app.services import auth as auth_service
from tests.support import add_barber, api_sign_in, api_sign_up

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
VERIFY = "/api/v1/auth/verify"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"

EMAIL = "aziza@example.com"


def _register(client, email=EMAIL, **extra):
    return client.post(REGISTER, json={"email": email, "full_name": "Aziza Karimova", **extra})


def _verify(client, code, email=EMAIL):
    return client.post(VERIFY, json={"email": email, "code": code})


def _wrong(code: str) -> str:
    """A well-formed code that is not `code`."""
    return "000000" if code != "000000" else "111111"


def _codes(db: Session) -> list[LoginCode]:
    return list(db.scalars(select(LoginCode).order_by(LoginCode.id)))


# --- asking for a code ------------------------------------------------------


def test_register_emails_a_code_and_creates_no_account_yet(client, db, mailbox):
    response = _register(client)

    assert response.status_code == 202
    assert response.json()["expires_in_minutes"] == 10
    assert db.scalar(select(func.count(User.id))) == 0  # only a proven code makes one
    [mail] = mailbox.to(EMAIL)
    assert mailbox.last_code(EMAIL) in mail.subject  # readable from a notification
    assert "expires in 10 minutes" in mail.body
    assert "Aziza Karimova" in mail.body


def test_the_code_is_stored_only_as_a_hash(client, db, mailbox):
    _register(client)

    [stored] = _codes(db)
    assert mailbox.last_code(EMAIL) not in stored.code_hash
    assert len(stored.code_hash) == 64  # hex SHA-256


def test_proving_the_code_creates_a_customer_and_signs_in(client, db, mailbox):
    _register(client, email="  Aziza@Example.COM ", full_name="  Aziza  ")

    response = _verify(client, mailbox.last_code(EMAIL), email=" AZIZA@example.com ")

    assert response.status_code == 200
    assert response.json()["token_type"] == "bearer"
    me = client.get(ME).json()  # the cookie jar holds the login cookie
    assert (me["email"], me["full_name"], me["role"]) == (EMAIL, "Aziza", "customer")
    assert db.scalar(select(User.role)) == UserRole.CUSTOMER


def test_register_cannot_create_a_barber(client, mailbox):
    # An extra `role` field is simply not part of the request model.
    _register(client, role="barber")
    _verify(client, mailbox.last_code(EMAIL))
    assert client.get(ME).json()["role"] == "customer"


@pytest.mark.parametrize(
    "body",
    [
        {"email": EMAIL, "full_name": ""},
        {"email": EMAIL, "full_name": "   "},  # only spaces would be stored as an empty name
        {"email": EMAIL, "full_name": "n" * 101},
        {"email": "not-an-email", "full_name": "Aziza"},
        {"email": "two@@example.com", "full_name": "Aziza"},
        {"email": "a@b", "full_name": "Aziza"},
        {"email": EMAIL},
    ],
)
def test_register_rejects_invalid_input_with_422(client, mailbox, body):
    response = client.post(REGISTER, json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert mailbox.sent == []


def test_login_emails_a_code_to_an_existing_account(client, mailbox):
    api_sign_up(client, mailbox)
    mailbox.sent.clear()
    client.cookies.clear()  # a request that carries the login cookie needs the CSRF header

    response = client.post(LOGIN, json={"email": " AZIZA@example.com "})

    assert response.status_code == 202
    assert len(mailbox.to(EMAIL)) == 1
    assert "Hello Aziza Karimova," in mailbox.to(EMAIL)[0].body


def test_signing_up_with_an_address_that_has_an_account_sends_a_sign_in_code(client, mailbox):
    """No "already registered" answer exists to probe; the name typed is ignored."""
    api_sign_up(client, mailbox)
    mailbox.sent.clear()
    client.cookies.clear()

    response = _register(client, full_name="Someone Else")

    assert response.status_code == 202
    assert _verify(client, mailbox.last_code(EMAIL)).status_code == 200
    assert client.get(ME).json()["full_name"] == "Aziza Karimova"


def test_asking_for_a_code_answers_the_same_for_everyone(client, db, mailbox):
    """An unknown address and a deactivated account look exactly like a real one."""
    api_sign_up(client, mailbox)
    client.cookies.clear()
    inactive = add_barber(db, "off@example.com", "Off")
    inactive.is_active = False
    db.flush()

    known = client.post(LOGIN, json={"email": EMAIL})
    unknown = client.post(LOGIN, json={"email": "nobody@example.com"})
    deactivated = client.post(LOGIN, json={"email": "off@example.com"})

    assert known.status_code == unknown.status_code == deactivated.status_code == 202
    assert known.json() == unknown.json() == deactivated.json()
    assert mailbox.to("nobody@example.com") == [] and mailbox.to("off@example.com") == []


def test_the_request_limit_trips_after_the_same_count_for_every_address(client, mailbox):
    """If only real accounts were counted, the 6th request would reveal who has one."""
    api_sign_up(client, mailbox)
    client.cookies.clear()
    for email in (EMAIL, "nobody@example.com"):
        sent = 1 if email == EMAIL else 0  # the sign-up above was the first for EMAIL
        for _ in range(auth_service.MAX_CODES_PER_WINDOW - sent):
            assert client.post(LOGIN, json={"email": email}).status_code == 202

        blocked = client.post(LOGIN, json={"email": email})

        assert blocked.status_code == 429, email
        assert blocked.json()["error"]["code"] == "TOO_MANY_CODES"
        assert blocked.headers["Retry-After"] == "600"


def test_the_request_limit_lifts_when_the_oldest_request_leaves_the_window(client, frozen_clock):
    for _ in range(auth_service.MAX_CODES_PER_WINDOW):
        client.post(LOGIN, json={"email": EMAIL})
    frozen_clock.advance(timedelta(minutes=10) - timedelta(seconds=1))

    blocked = client.post(LOGIN, json={"email": EMAIL})
    assert (blocked.status_code, blocked.headers["Retry-After"]) == (429, "1")

    frozen_clock.advance(timedelta(seconds=1))
    assert client.post(LOGIN, json={"email": EMAIL}).status_code == 202


def test_a_mail_server_that_is_down_is_a_503_not_a_silent_success(client, mailbox):
    mailbox.fail = True

    response = _register(client)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "EMAIL_SEND_FAILED"


def test_a_failed_send_leaves_no_code_behind(db, mailbox, frozen_clock):
    """The row is written in the request's transaction, so the failure that aborts the
    request takes it along. Here the transaction is a savepoint."""
    mailbox.fail = True

    with pytest.raises(AppError) as caught, db.begin_nested():
        auth_service.request_registration_code(
            db, mailbox, email=EMAIL, full_name="Aziza", now=frozen_clock.now()
        )

    assert caught.value.code == "EMAIL_SEND_FAILED"
    assert _codes(db) == []


def test_old_code_rows_are_cleared_out_when_a_new_one_is_asked_for(client, db, frozen_clock):
    client.post(LOGIN, json={"email": EMAIL})
    frozen_clock.advance(auth_service.KEEP_CODES_FOR + timedelta(seconds=1))

    client.post(LOGIN, json={"email": EMAIL})

    assert len(_codes(db)) == 1


# --- proving the code -------------------------------------------------------


def test_verify_returns_a_bearer_token_that_opens_me(client, mailbox):
    _register(client)

    body = _verify(client, mailbox.last_code(EMAIL)).json()

    client.cookies.clear()  # prove the header alone is enough
    me = client.get(ME, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == EMAIL


def test_verify_sets_an_httponly_lax_cookie_that_opens_me(client, mailbox):
    _register(client)

    response = _verify(client, mailbox.last_code(EMAIL))

    cookie = response.headers["set-cookie"].lower()
    assert "access_token=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "secure" not in cookie  # test environment is plain http
    assert client.get(ME).json()["email"] == EMAIL  # cookie jar sends it


def test_login_cookie_is_secure_in_production(client, mailbox, monkeypatch):
    _register(client)
    production = Settings(app_env="production", jwt_secret="x" * 40, smtp_host="smtp.example.com")
    monkeypatch.setattr("app.api.cookies.get_settings", lambda: production)

    set_cookies = _verify(client, mailbox.last_code(EMAIL)).headers.get_list("set-cookie")

    assert len(set_cookies) == 2  # the login cookie and the CSRF cookie
    assert all("secure" in cookie.lower() for cookie in set_cookies)


def test_the_code_may_be_pasted_with_a_space_or_dash(client, mailbox):
    _register(client)
    code = mailbox.last_code(EMAIL)

    assert _verify(client, f"{code[:3]} {code[3:]}").status_code == 200


@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", "12 34 5a", ""])
def test_a_code_that_is_not_six_digits_is_422(client, code):
    response = _verify(client, code)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_every_kind_of_bad_code_gets_the_identical_answer(client, mailbox, frozen_clock):
    """Wrong, expired, used, replaced and never-asked-for must not tell a guesser apart."""
    api_sign_up(client, mailbox)  # a used code
    client.cookies.clear()
    used = mailbox.last_code(EMAIL)
    client.post(LOGIN, json={"email": EMAIL})
    stale = mailbox.last_code(EMAIL)
    client.post(LOGIN, json={"email": EMAIL})  # replaces `stale`
    live = mailbox.last_code(EMAIL)

    answers = [
        _verify(client, used),
        _verify(client, stale),
        _verify(client, _wrong(live)),
        _verify(client, "123456", email="nobody@example.com"),
    ]
    frozen_clock.advance(timedelta(hours=1))
    answers.append(_verify(client, live))  # expired

    assert {a.status_code for a in answers} == {401}
    assert all(a.json() == answers[0].json() for a in answers)
    assert answers[0].json()["error"]["code"] == "INVALID_CODE"


def test_a_code_expires_at_exactly_ten_minutes(client, mailbox, frozen_clock):
    _register(client)
    code = mailbox.last_code(EMAIL)
    frozen_clock.advance(timedelta(minutes=10))

    response = _verify(client, code)

    assert (response.status_code, response.json()["error"]["code"]) == (401, "INVALID_CODE")


def test_the_last_second_before_expiry_still_works(client, mailbox, frozen_clock):
    _register(client)
    frozen_clock.advance(timedelta(minutes=10) - timedelta(seconds=1))

    assert _verify(client, mailbox.last_code(EMAIL)).status_code == 200


def test_a_code_works_once(client, mailbox):
    _register(client)
    code = mailbox.last_code(EMAIL)

    assert _verify(client, code).status_code == 200
    client.cookies.clear()  # a request that carries the login cookie needs the CSRF header
    again = _verify(client, code)

    assert (again.status_code, again.json()["error"]["code"]) == (401, "INVALID_CODE")


@pytest.fixture
def codes(monkeypatch):
    """Makes the app issue 111111, 222222, 333333... so a test knows which is which."""
    numbers = iter(f"{n}{n}{n}{n}{n}{n}" for n in range(1, 10))
    monkeypatch.setattr(auth_service, "generate_login_code", lambda: next(numbers))


def test_asking_again_replaces_the_earlier_code(client, db, mailbox, codes):
    db.add(User(email=EMAIL, full_name="Aziza"))
    db.flush()
    client.post(LOGIN, json={"email": EMAIL})  # 111111
    client.post(LOGIN, json={"email": EMAIL})  # 222222

    assert _verify(client, "111111").status_code == 401
    assert _verify(client, "222222").status_code == 200


def test_a_code_only_works_for_the_address_it_was_sent_to(client, mailbox, codes):
    _register(client, email="aziza@example.com")  # 111111
    _register(client, email="bobur@example.com")  # 222222

    assert _verify(client, "111111", email="bobur@example.com").status_code == 401
    assert _verify(client, "222222", email="bobur@example.com").status_code == 200


def test_a_code_dies_after_five_wrong_tries_even_if_the_next_one_is_right(
    db, mailbox, frozen_clock
):
    """Called on the service with a roomy IP limiter, so the per-code cap is what stops it."""
    auth_service.request_registration_code(
        db, mailbox, email=EMAIL, full_name="Aziza", now=frozen_clock.now()
    )
    code = mailbox.last_code(EMAIL)
    limiter = InMemoryLoginLimiter(max_attempts=100, window_seconds=300)

    def attempt(guess):
        return auth_service.verify_code(
            db, limiter, email=EMAIL, code=guess, client_ip="1.2.3.4", now=frozen_clock.now()
        )

    for _ in range(auth_service.MAX_WRONG_TRIES):
        with pytest.raises(AppError) as caught:
            attempt(_wrong(code))
        assert caught.value.code == "INVALID_CODE"

    with pytest.raises(AppError) as caught:
        attempt(code)  # right, but the code is spent
    assert caught.value.code == "INVALID_CODE"
    assert _codes(db)[0].failed_attempts == auth_service.MAX_WRONG_TRIES


def test_a_wrong_try_is_counted_even_though_the_request_fails(client, db, mailbox):
    """The counter is committed in the service, so the failing request cannot roll it back."""
    _register(client)
    code = mailbox.last_code(EMAIL)

    _verify(client, _wrong(code))

    assert _codes(db)[0].failed_attempts == 1


def test_a_deactivated_account_is_refused_once_the_code_is_right(client, db, mailbox):
    api_sign_up(client, mailbox)
    client.cookies.clear()
    client.post(LOGIN, json={"email": EMAIL})
    code = mailbox.last_code(EMAIL)
    db.scalar(select(User).where(User.email == EMAIL)).is_active = False
    db.flush()

    response = _verify(client, code)

    assert (response.status_code, response.json()["error"]["code"]) == (401, "ACCOUNT_INACTIVE")


def test_a_sign_in_code_for_an_address_without_an_account_proves_nothing(client, db, mailbox):
    """Even if the code were somehow right, a sign-in (no name) must not create an account."""
    client.post(LOGIN, json={"email": "nobody@example.com"})
    row = _codes(db)[0]
    row.code_hash = hash_login_code("nobody@example.com", "123456")  # as if it had been known
    db.flush()

    response = _verify(client, "123456", email="nobody@example.com")

    assert (response.status_code, response.json()["error"]["code"]) == (401, "INVALID_CODE")
    assert db.scalar(select(func.count(User.id))) == 0


def test_losing_the_sign_up_race_signs_in_to_the_account_that_won(client, db, mailbox, monkeypatch):
    """Two sign-ups for one address both find no account; the unique index decides."""
    _register(client)
    code = mailbox.last_code(EMAIL)
    winner = User(email=EMAIL, full_name="Won The Race")
    db.add(winner)
    db.flush()
    real = auth_service._find_by_email
    calls = []

    def blind_the_first_time(db, email):
        calls.append(email)
        return None if len(calls) == 1 else real(db, email)

    monkeypatch.setattr(auth_service, "_find_by_email", blind_the_first_time)

    response = _verify(client, code)

    assert response.status_code == 200
    assert client.get(ME).json()["full_name"] == "Won The Race"
    # The failed insert was rolled back to a savepoint: the session still works.
    assert db.scalar(select(func.count(User.id))) == 1


# --- logout -----------------------------------------------------------------


def test_logout_clears_the_cookie(client, mailbox):
    api_sign_up(client, mailbox)
    assert client.get(ME).status_code == 200

    response = client.post(LOGOUT, headers={"X-CSRF-Token": client.cookies["csrf_token"]})

    assert response.status_code == 204
    cleared = " ".join(response.headers.get_list("set-cookie"))
    assert "access_token=" in cleared and "csrf_token=" in cleared
    assert "Max-Age=0" in cleared
    assert client.get(ME).status_code == 401
    assert "csrf_token" not in client.cookies


def test_logout_works_when_not_logged_in(client):
    assert client.post(LOGOUT).status_code == 204


# --- me ---------------------------------------------------------------------


def test_me_without_credentials_is_401_in_the_error_envelope(client):
    response = client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_with_a_garbage_bearer_token_is_401_even_if_the_cookie_is_good(client, mailbox):
    """The Bearer header wins; a bad one is not quietly replaced by the cookie."""
    api_sign_up(client, mailbox)  # the cookie jar now holds a valid cookie

    response = client.get(ME, headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_me_with_an_expired_token_is_401(client, mailbox, frozen_clock):
    api_sign_up(client, mailbox)
    frozen_clock.advance(timedelta(days=2))

    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_a_valid_token_stops_working_once_the_user_is_deactivated(client, db, mailbox):
    api_sign_up(client, mailbox)
    assert client.get(ME).status_code == 200
    db.scalar(select(User).where(User.email == EMAIL)).is_active = False
    db.flush()

    response = client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"


def test_a_barber_signs_in_with_a_code_like_everyone(client, db, mailbox):
    barber = add_barber(db, "boss@example.com", "Boss")

    api_sign_in(client, mailbox, email="boss@example.com")

    me = client.get(ME).json()
    assert (me["role"], me["provider_id"]) == ("barber", barber.provider_id)


def test_me_gives_a_barber_their_provider_id_and_a_customer_none(client, barber, customer):
    """A barber needs their provider id for `/providers/{id}/...` (found by the walkthrough)."""
    assert client.get("/api/v1/auth/me", headers=customer).json()["provider_id"] is None
    me = client.get("/api/v1/auth/me", headers=barber).json()
    assert me["role"] == "barber"
    assert me["provider_id"] == barber.provider.id
