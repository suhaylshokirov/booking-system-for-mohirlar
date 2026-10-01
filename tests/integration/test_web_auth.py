"""Sign in, create an account and sign out in the browser (P8.2)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.api.deps import CurrentUser, get_login_limiter
from app.core.clock import FrozenClock, get_clock
from app.core.db import get_db
from app.core.rate_limit import InMemoryLoginLimiter
from app.core.security import hash_password
from app.main import create_app
from app.models.user import User, UserRole
from tests.support import add_barber

PASSWORD = "a long passphrase"


@pytest.fixture
def aziza(db: Session) -> User:
    user = User(
        email="aziza@example.com",
        password_hash=hash_password(PASSWORD),
        full_name="Aziza Karimova",
        role=UserRole.CUSTOMER,
    )
    db.add(user)
    db.flush()
    return user


def _csrf(client: TestClient) -> str:
    """Open the login page like a browser would, and return the form's token."""
    client.get("/login")
    return client.cookies[CSRF_COOKIE]


def _login(client: TestClient, email: str = "aziza@example.com", password: str = PASSWORD, **extra):
    data = {"email": email, "password": password, "csrf_token": _csrf(client), **extra}
    return client.post("/login", data=data, follow_redirects=False)


def _register(client: TestClient, **overrides):
    data = {
        "full_name": "Bobur Aliyev",
        "email": "bobur@example.com",
        "password": PASSWORD,
        "csrf_token": _csrf(client),
        **overrides,
    }
    return client.post("/register", data=data, follow_redirects=False)


# --- The forms -----------------------------------------------------------------


def test_login_page_puts_the_csrf_cookie_value_in_the_form(client):
    response = client.get("/login")

    token = response.cookies[CSRF_COOKIE]
    assert f'name="csrf_token" value="{token}"' in response.text


def test_auth_forms_submit_once_and_leave_validation_to_the_server(client):
    for path in ("/login", "/register"):
        html = client.get(path).text
        assert "novalidate data-submit-once" in html
        assert "data-busy-label=" in html


def test_visitor_sees_a_sign_in_link_in_the_header(client):
    html = client.get("/").text

    assert 'href="/login">Sign in</a>' in html
    assert "Sign out" not in html


# --- Register --------------------------------------------------------------------


def test_register_signs_the_person_in_and_greets_them(client):
    response = _register(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert ACCESS_COOKIE in response.cookies

    home = client.get("/").text
    assert "Your account is ready, and you&#39;re signed in." in home
    assert '<span class="account-name">Bobur</span>' in home
    assert "Sign out" in home


def test_register_goes_on_to_a_same_site_next(client):
    response = _register(client, next="/book/3")

    assert response.headers["location"] == "/book/3"


def test_invalid_registration_shows_field_messages_and_keeps_what_was_typed(client):
    response = _register(client, email="bobur@example", password="short", full_name="   ")

    assert response.status_code == 422
    html = response.text
    assert "Enter your name, so the business knows who is coming." in html
    assert "Enter an email address like name@example.com." in html
    assert "Use at least 8 characters." in html
    assert 'value="bobur@example"' in html
    assert 'value="short"' not in html  # a password is never sent back
    assert 'aria-invalid="true"' in html
    assert ACCESS_COOKIE not in response.cookies


def test_registering_a_taken_email_offers_to_sign_in_instead(client, aziza):
    response = _register(client, email="AZIZA@example.com")

    assert response.status_code == 409
    assert "An account with this email already exists." in response.text
    assert "Sign in instead" in response.text


def test_register_without_a_csrf_token_is_a_403_page(client):
    response = client.post(
        "/register",
        data={"full_name": "Bobur", "email": "bobur@example.com", "password": PASSWORD},
    )

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("text/html")
    assert "This form has expired" in response.text


# --- Log in ------------------------------------------------------------------------


def test_login_signs_in_and_redirects_home_with_a_notice(client, aziza):
    response = _login(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert ACCESS_COOKIE in response.cookies
    assert "You&#39;re signed in." in client.get("/").text


def test_login_rotates_the_csrf_token(client, aziza):
    before = _csrf(client)

    _login(client)

    assert client.cookies[CSRF_COOKIE] != before


def test_bad_login_shows_the_error_and_keeps_the_email(client, aziza):
    response = _login(client, password="not the password")

    assert response.status_code == 401
    assert "Incorrect email or password." in response.text
    assert 'value="aziza@example.com"' in response.text
    assert ACCESS_COOKIE not in response.cookies


def test_empty_login_form_asks_for_both_fields(client):
    response = _login(client, email="", password="")

    assert response.status_code == 422
    assert "Enter an email address like name@example.com." in response.text
    assert "Enter your password." in response.text


def test_login_without_a_csrf_token_is_a_403_page(client, aziza):
    """Login CSRF: a form on another site cannot sign a browser in."""
    response = client.post("/login", data={"email": "aziza@example.com", "password": PASSWORD})

    assert response.status_code == 403
    assert "This form has expired" in response.text
    assert ACCESS_COOKIE not in response.cookies


def test_login_goes_on_to_a_same_site_next(client, aziza):
    response = _login(client, next="/me/bookings?tab=past")

    assert response.headers["location"] == "/me/bookings?tab=past"


@pytest.mark.parametrize(
    "evil", ["https://evil.example", "//evil.example", "/\\evil.example", "/\t/evil.example"]
)
def test_open_redirect_next_is_ignored(client, aziza, evil):
    response = _login(client, next=evil)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_open_redirect_next_is_not_echoed_into_the_form(client):
    html = client.get("/login", params={"next": "https://evil.example"}).text

    assert "evil.example" not in html
    assert '<input type="hidden" name="next" value="/">' in html


def test_too_many_failed_logins_are_refused_with_retry_after(client, aziza):
    for _ in range(5):
        _login(client, password="wrong guess")

    response = _login(client)  # even the right password, while blocked

    assert response.status_code == 429
    assert "Too many failed login attempts" in response.text
    assert int(response.headers["retry-after"]) > 0


def test_signed_in_person_opening_login_or_register_is_sent_on(client, aziza):
    _login(client)

    for path in ("/login", "/register"):
        response = client.get(path, params={"next": "/book/3"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/book/3"


# --- Log out ---------------------------------------------------------------------


def test_logout_ends_the_session_and_says_so(client, aziza):
    _login(client)
    token = client.cookies[CSRF_COOKIE]

    response = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert f'{ACCESS_COOKIE}=""' in response.headers["set-cookie"]
    home = client.get("/").text
    assert "You&#39;re signed out." in home
    assert 'href="/login">Sign in</a>' in home


def test_logout_without_the_csrf_token_is_refused(client, aziza):
    """Otherwise any site could sign a visitor out with a hidden form."""
    _login(client)

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 403
    assert "Sign out" in client.get("/").text  # still signed in


def test_signed_in_header_has_a_confirmed_sign_out_form(client, aziza):
    _login(client)

    html = client.get("/").text

    assert 'action="/logout"' in html
    assert 'data-confirm="Sign out?"' in html
    assert f'name="csrf_token" value="{client.cookies[CSRF_COOKIE]}"' in html


# --- Pages that need a signed-in person -----------------------------------------------


@pytest.fixture
def client_with_private_page(db: Session, frozen_clock: FrozenClock) -> Iterator[TestClient]:
    app = create_app()

    @app.get("/test/private")
    def private(user: CurrentUser):
        return {"id": user.id}

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clock] = lambda: frozen_clock
    limiter = InMemoryLoginLimiter(max_attempts=5, window_seconds=300)
    app.dependency_overrides[get_login_limiter] = lambda: limiter
    with TestClient(app) as test_client:
        yield test_client


def test_a_page_that_needs_sign_in_sends_a_visitor_to_login_and_back(
    client_with_private_page, aziza
):
    client = client_with_private_page

    response = client.get("/test/private", params={"x": "1"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Ftest%2Fprivate%3Fx%3D1"

    after = _login(client, next="/test/private?x=1")
    assert after.headers["location"] == "/test/private?x=1"
    assert client.get("/test/private?x=1").json() == {"id": aziza.id}


# --- The demo barber shortcut -------------------------------------------------------------


def _demo_settings(monkeypatch, app_env="development"):
    from app.core.config import Settings
    from app.web import auth as web_auth

    settings = Settings(
        app_env=app_env,
        jwt_secret="a-real-secret-for-this-test",
        smtp_host="smtp.example.com",
        barber_email="boss@example.com",
        barber_password=PASSWORD,
    )
    monkeypatch.setattr(web_auth, "get_settings", lambda: settings)


@pytest.fixture
def boss(db: Session) -> User:
    user = add_barber(db, "boss@example.com", "Boss")
    user.password_hash = hash_password(PASSWORD)
    db.flush()
    return user


def test_the_login_page_offers_the_demo_barber_outside_production(client, monkeypatch):
    _demo_settings(monkeypatch)

    html = client.get("/login").text

    assert "/login/demo-barber" in html
    assert "boss@example.com" in html


def test_the_demo_button_signs_in_the_barber_and_opens_the_dashboard(client, monkeypatch, boss):
    _demo_settings(monkeypatch)

    response = client.post(
        "/login/demo-barber", data={"csrf_token": _csrf(client)}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/barber"
    assert client.get("/barber").status_code == 200  # the cookie works


def test_the_demo_button_explains_a_missing_barber(client, monkeypatch):
    _demo_settings(monkeypatch)

    response = client.post("/login/demo-barber", data={"csrf_token": _csrf(client)})

    assert response.status_code == 401
    assert "scripts.seed" in response.text


def test_production_has_no_demo_barber(client, monkeypatch, boss):
    _demo_settings(monkeypatch, "production")

    assert "demo-barber" not in client.get("/login").text
    response = client.post(
        "/login/demo-barber", data={"csrf_token": _csrf(client)}, follow_redirects=False
    )
    assert response.status_code == 404
