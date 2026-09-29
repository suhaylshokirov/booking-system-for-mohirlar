"""/auth/register, /login, /logout, /me against a real PostgreSQL (P2.2)."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.user import User, UserRole
from app.services import auth as auth_service

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"

PASSWORD = "a long passphrase"


def _register(client, email="aziza@example.com", password=PASSWORD, **extra):
    body = {"email": email, "password": password, "full_name": "Aziza Karimova", **extra}
    return client.post(REGISTER, json=body)


def _login(client, email="aziza@example.com", password=PASSWORD):
    return client.post(LOGIN, json={"email": email, "password": password})


# --- register --------------------------------------------------------------


def test_register_creates_a_customer_and_never_returns_the_password(client, db: Session):
    response = _register(client)

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "aziza@example.com"
    assert body["full_name"] == "Aziza Karimova"
    assert body["role"] == "customer"
    assert "password" not in body and "password_hash" not in body
    stored = db.scalar(select(User).where(User.id == body["id"]))
    assert stored.password_hash.startswith("$argon2")


def test_register_normalises_the_email_and_trims_the_name(client):
    response = _register(client, email="  Aziza@Example.COM ", full_name="  Aziza  ")
    assert response.status_code == 201
    assert response.json()["email"] == "aziza@example.com"


def test_register_cannot_create_an_admin(client):
    # An extra `role` field is simply not part of the request model.
    response = _register(client, role="admin")
    assert response.status_code == 201
    assert response.json()["role"] == "customer"


def test_registering_the_same_email_in_another_case_is_a_conflict(client):
    assert _register(client, email="aziza@example.com").status_code == 201

    response = _register(client, email="AZIZA@example.com")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"


def test_losing_the_registration_race_is_still_a_clean_409(client, db, monkeypatch):
    """Two requests pass the friendly pre-check together; the unique index decides."""
    assert _register(client).status_code == 201
    monkeypatch.setattr(auth_service, "_find_by_email", lambda db, email: None)

    response = _register(client, email="Aziza@example.com")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "EMAIL_TAKEN"
    # The failed insert was rolled back to a savepoint: the session still works.
    assert db.scalar(select(User.id).limit(1)) is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"password": "short77"},  # 7 characters
        {"password": "x" * 129},
        {"full_name": ""},
        {"full_name": "n" * 101},
        {"email": "not-an-email"},
        {"email": "two@@example.com"},
        {"email": "a@b"},
    ],
)
def test_register_rejects_invalid_input_with_422(client, overrides):
    body = {"email": "aziza@example.com", "password": PASSWORD, "full_name": "Aziza"}
    response = client.post(REGISTER, json={**body, **overrides})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_register_accepts_the_boundary_password_lengths(client):
    assert _register(client, email="a@example.com", password="x" * 8).status_code == 201
    assert _register(client, email="b@example.com", password="x" * 128).status_code == 201


# --- login -----------------------------------------------------------------


def test_login_returns_a_bearer_token_that_opens_me(client):
    _register(client)

    response = _login(client)

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    client.cookies.clear()  # prove the header alone is enough
    me = client.get(ME, headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "aziza@example.com"


def test_login_sets_an_httponly_lax_cookie_that_opens_me(client):
    _register(client)

    response = _login(client)

    cookie = response.headers["set-cookie"].lower()
    assert "access_token=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie
    assert "path=/" in cookie
    assert "secure" not in cookie  # test environment is plain http
    assert client.get(ME).json()["email"] == "aziza@example.com"  # cookie jar sends it


def test_login_cookie_is_secure_in_production(client, monkeypatch):
    _register(client)
    production = Settings(app_env="production", jwt_secret="x" * 40)
    monkeypatch.setattr("app.api.cookies.get_settings", lambda: production)

    set_cookies = _login(client).headers.get_list("set-cookie")
    assert len(set_cookies) == 2  # the login cookie and the CSRF cookie
    assert all("secure" in cookie.lower() for cookie in set_cookies)


def test_login_ignores_email_case_and_padding(client):
    _register(client)
    assert _login(client, email=" AZIZA@Example.com ").status_code == 200


def test_unknown_email_and_wrong_password_give_identical_responses(client):
    _register(client)

    unknown = _login(client, email="nobody@example.com")
    wrong = _login(client, password="wrong password")

    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()
    assert unknown.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_unknown_email_still_pays_for_a_password_check(client, monkeypatch):
    """Skipping the hash for unknown emails would make them measurably faster."""
    calls = []
    real = auth_service.verify_password
    monkeypatch.setattr(auth_service, "verify_password", lambda p, h: calls.append(h) or real(p, h))

    _login(client, email="nobody@example.com")

    assert len(calls) == 1


def test_deactivated_user_cannot_log_in_but_only_learns_it_with_the_right_password(client, db):
    user_id = _register(client).json()["id"]
    db.get(User, user_id).is_active = False
    db.flush()

    right = _login(client)
    wrong = _login(client, password="wrong password")

    assert (right.status_code, right.json()["error"]["code"]) == (401, "ACCOUNT_INACTIVE")
    assert (wrong.status_code, wrong.json()["error"]["code"]) == (401, "INVALID_CREDENTIALS")


def test_login_with_a_missing_field_is_422(client):
    assert client.post(LOGIN, json={"email": "aziza@example.com"}).status_code == 422


# --- logout ----------------------------------------------------------------


def test_logout_clears_the_cookie(client):
    _register(client)
    _login(client)
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


# --- me --------------------------------------------------------------------


def test_me_without_credentials_is_401_in_the_error_envelope(client):
    response = client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHENTICATED"


def test_me_with_a_garbage_bearer_token_is_401_even_if_the_cookie_is_good(client):
    """The Bearer header wins; a bad one is not quietly replaced by the cookie."""
    _register(client)
    _login(client)  # the cookie jar now holds a valid cookie

    response = client.get(ME, headers={"Authorization": "Bearer garbage"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_TOKEN"


def test_me_with_an_expired_token_is_401(client, frozen_clock):
    _register(client)
    _login(client)
    frozen_clock.advance(timedelta(days=2))

    response = client.get(ME)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_a_valid_token_stops_working_once_the_user_is_deactivated(client, db):
    user_id = _register(client).json()["id"]
    _login(client)
    assert client.get(ME).status_code == 200

    db.get(User, user_id).is_active = False
    db.flush()

    response = client.get(ME)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"


def test_registered_users_are_customers_in_the_database(client, db):
    _register(client)
    assert db.scalar(select(User.role)) == UserRole.CUSTOMER
