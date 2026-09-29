"""Double-submit CSRF protection (P2.4).

The app-wide `csrf_protect` dependency is exercised on the real app plus a few
probe routes: no unsafe endpoint exists yet other than the auth ones.
"""

from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import Depends, Form, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.cookies import ensure_csrf_cookie
from app.api.csrf import require_csrf
from app.api.deps import CurrentUser
from app.core.clock import FrozenClock, get_clock
from app.core.db import get_db
from app.main import create_app

LOGIN = "/api/v1/auth/login"
REGISTER = "/api/v1/auth/register"
PASSWORD = "a long passphrase"


@pytest.fixture
def client(db: Session, frozen_clock: FrozenClock) -> Iterator[TestClient]:
    """The real app plus probe routes, wired like the shared `client` fixture."""
    app = create_app()

    @app.post("/probe")
    def probe(user: CurrentUser) -> dict:
        return {"ok": True}

    @app.put("/probe")
    def probe_put(user: CurrentUser) -> dict:
        return {"ok": True}

    @app.delete("/probe")
    def probe_delete(user: CurrentUser) -> dict:
        return {"ok": True}

    @app.post("/form-probe")
    def form_probe(user: CurrentUser, note: Annotated[str, Form()]) -> dict:
        return {"note": note}

    @app.get("/form-page")
    def form_page(request: Request, response: Response) -> dict:
        return {"token": ensure_csrf_cookie(request, response)}

    @app.post("/prelogin-form", dependencies=[Depends(require_csrf)])
    def prelogin_form(email: Annotated[str, Form()]) -> dict:
        return {"email": email}

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clock] = lambda: frozen_clock
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def logged_in(client: TestClient) -> TestClient:
    """The client after register + login: it holds both cookies, and the jar sends them."""
    client.post(REGISTER, json={"email": "a@example.com", "password": PASSWORD, "full_name": "A"})
    assert (
        client.post(LOGIN, json={"email": "a@example.com", "password": PASSWORD}).status_code == 200
    )
    return client


def _assert_csrf_failed(response) -> None:
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_FAILED"


# --- what login hands out --------------------------------------------------


def test_login_sets_a_csrf_cookie_that_scripts_can_read(logged_in):
    assert logged_in.cookies.get("csrf_token")


def test_login_cookie_flags(client):
    client.post(REGISTER, json={"email": "a@example.com", "password": PASSWORD, "full_name": "A"})
    response = client.post(LOGIN, json={"email": "a@example.com", "password": PASSWORD})

    by_name = {c.split("=", 1)[0]: c.lower() for c in response.headers.get_list("set-cookie")}
    assert "httponly" in by_name["access_token"]
    assert "httponly" not in by_name["csrf_token"]  # the page has to read this one
    assert "samesite=lax" in by_name["csrf_token"]


def test_every_login_issues_a_new_csrf_token(client):
    client.post(REGISTER, json={"email": "a@example.com", "password": PASSWORD, "full_name": "A"})
    credentials = {"email": "a@example.com", "password": PASSWORD}
    client.post(LOGIN, json=credentials)
    first = client.cookies["csrf_token"]

    # Logging in again while holding the cookies is itself a cookie POST.
    client.post(LOGIN, json=credentials, headers={"X-CSRF-Token": first})

    assert client.cookies["csrf_token"] != first


# --- cookie-authenticated unsafe requests ----------------------------------


def test_cookie_post_without_a_token_is_403(logged_in):
    _assert_csrf_failed(logged_in.post("/probe"))


def test_cookie_post_with_the_token_in_the_header_succeeds(logged_in):
    headers = {"X-CSRF-Token": logged_in.cookies["csrf_token"]}
    assert logged_in.post("/probe", headers=headers).status_code == 200


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_every_unsafe_method_is_checked(logged_in, method):
    send = getattr(logged_in, method)
    _assert_csrf_failed(send("/probe"))
    assert (
        send("/probe", headers={"X-CSRF-Token": logged_in.cookies["csrf_token"]}).status_code == 200
    )


def test_cookie_post_with_a_mismatched_token_is_403(logged_in):
    _assert_csrf_failed(logged_in.post("/probe", headers={"X-CSRF-Token": "not-the-token"}))


def test_a_token_without_the_matching_cookie_is_403(logged_in):
    """An attacker who guesses a header value still cannot set the cookie half."""
    token = logged_in.cookies["csrf_token"]
    del logged_in.cookies["csrf_token"]
    _assert_csrf_failed(logged_in.post("/probe", headers={"X-CSRF-Token": token}))


def test_an_empty_token_with_an_empty_cookie_is_403(logged_in):
    logged_in.cookies.set("csrf_token", "")
    _assert_csrf_failed(logged_in.post("/probe", headers={"X-CSRF-Token": ""}))


def test_safe_methods_need_no_token(logged_in):
    assert logged_in.get("/api/v1/auth/me").status_code == 200


def test_form_field_is_accepted_and_the_endpoint_still_reads_its_own_fields(logged_in):
    token = logged_in.cookies["csrf_token"]
    response = logged_in.post("/form-probe", data={"csrf_token": token, "note": "hello"})
    assert response.status_code == 200
    assert response.json() == {"note": "hello"}


def test_wrong_form_field_is_403(logged_in):
    _assert_csrf_failed(logged_in.post("/form-probe", data={"csrf_token": "nope", "note": "x"}))


def test_a_csrf_field_inside_a_json_body_does_not_count(logged_in):
    token = logged_in.cookies["csrf_token"]
    _assert_csrf_failed(logged_in.post("/probe", json={"csrf_token": token}))


# --- Bearer requests are exempt --------------------------------------------


def _bearer_from_login(client: TestClient) -> str:
    response = client.post(LOGIN, json={"email": "a@example.com", "password": PASSWORD})
    return response.json()["access_token"]


def test_bearer_post_needs_no_csrf_token(client):
    client.post(REGISTER, json={"email": "a@example.com", "password": PASSWORD, "full_name": "A"})
    token = _bearer_from_login(client)
    client.cookies.clear()  # a plain API client: no cookie jar

    response = client.post("/probe", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_bearer_post_is_exempt_even_when_the_browser_also_sends_cookies(logged_in):
    token = logged_in.post(
        LOGIN,
        json={"email": "a@example.com", "password": PASSWORD},
        headers={"X-CSRF-Token": logged_in.cookies["csrf_token"]},
    ).json()["access_token"]
    response = logged_in.post("/probe", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_a_non_bearer_authorization_header_does_not_bypass_csrf(logged_in):
    """`Basic` is ignored by our auth (the cookie is used), so it must not skip the check."""
    _assert_csrf_failed(logged_in.post("/probe", headers={"Authorization": "Basic YTpi"}))


# --- requests with no login cookie -----------------------------------------


def test_anonymous_api_calls_are_not_blocked_by_csrf(client):
    """Register and login by curl have no cookie to abuse, so they need no token."""
    response = client.post(
        REGISTER, json={"email": "b@example.com", "password": PASSWORD, "full_name": "B"}
    )
    assert response.status_code == 201


def test_anonymous_probe_fails_on_auth_not_on_csrf(client):
    response = client.post("/probe")
    assert response.status_code == 401


# --- pre-session forms (login / register pages) ----------------------------


def test_form_page_issues_a_csrf_cookie_and_reuses_it(client):
    first = client.get("/form-page").json()["token"]
    assert client.cookies["csrf_token"] == first

    assert client.get("/form-page").json()["token"] == first  # a second tab keeps the same one


def test_prelogin_form_without_a_token_is_403_even_with_no_cookies(client):
    _assert_csrf_failed(client.post("/prelogin-form", data={"email": "a@example.com"}))


def test_prelogin_form_with_the_issued_token_succeeds(client):
    token = client.get("/form-page").json()["token"]
    response = client.post("/prelogin-form", data={"email": "a@example.com", "csrf_token": token})
    assert response.status_code == 200
    assert response.json() == {"email": "a@example.com"}


def test_prelogin_form_with_a_forged_token_is_403(client):
    client.get("/form-page")
    _assert_csrf_failed(
        client.post("/prelogin-form", data={"email": "a@example.com", "csrf_token": "forged"})
    )
