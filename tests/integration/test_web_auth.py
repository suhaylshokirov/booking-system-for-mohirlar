"""Sign in, sign up and sign out in the browser: two pages each, an email then the code."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.api.deps import CurrentUser, get_login_limiter
from app.core.clock import FrozenClock, get_clock
from app.core.db import get_db
from app.core.mail import get_mailer
from app.core.rate_limit import InMemoryLoginLimiter
from app.main import create_app
from app.models.user import User, UserRole
from tests.support import Mailbox, add_barber


@pytest.fixture
def aziza(db: Session) -> User:
    user = User(
        email="aziza@example.com",
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


def _ask_login(client: TestClient, email: str = "aziza@example.com", **extra):
    """Step 1 of signing in: the email form."""
    data = {"email": email, "csrf_token": _csrf(client), **extra}
    return client.post("/login", data=data, follow_redirects=False)


def _ask_register(client: TestClient, **overrides):
    """Step 1 of signing up: the name and email form."""
    data = {
        "full_name": "Bobur Aliyev",
        "email": "bobur@example.com",
        "csrf_token": _csrf(client),
        **overrides,
    }
    return client.post("/register", data=data, follow_redirects=False)


def _enter_code(client: TestClient, code: str, email: str = "aziza@example.com", **extra):
    """Step 2: the code form."""
    data = {"email": email, "code": code, "csrf_token": _csrf(client), **extra}
    return client.post("/login/code", data=data, follow_redirects=False)


def _login(client: TestClient, mailbox: Mailbox, email: str = "aziza@example.com", **extra):
    """Both steps of signing in; returns the answer to the code form."""
    asked = _ask_login(client, email, **extra)
    assert asked.status_code == 303, asked.text
    return _enter_code(client, mailbox.last_code(email), email, **extra)


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


# --- Sign up ---------------------------------------------------------------------


def test_register_emails_a_code_and_opens_the_code_page(client, mailbox):
    response = _ask_register(client)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login/code?")
    assert "email=bobur%40example.com" in response.headers["location"]
    assert ACCESS_COOKIE not in response.cookies  # nobody is signed in by asking
    assert len(mailbox.to("bobur@example.com")) == 1


def test_proving_the_code_creates_the_account_signs_in_and_greets(client, mailbox, db):
    _ask_register(client)

    response = _enter_code(client, mailbox.last_code("bobur@example.com"), "bobur@example.com")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert ACCESS_COOKIE in response.cookies
    home = client.get("/").text
    assert "You&#39;re signed in." in home
    assert '<span class="account-name">Bobur</span>' in home
    assert "Sign out" in home
    assert (
        db.scalar(select(User.full_name).where(User.email == "bobur@example.com")) == "Bobur Aliyev"
    )


def test_register_goes_on_to_a_same_site_next(client, mailbox):
    asked = _ask_register(client, next="/book/3")
    assert "next=%2Fbook%2F3" in asked.headers["location"]

    response = _enter_code(
        client, mailbox.last_code("bobur@example.com"), "bobur@example.com", next="/book/3"
    )

    assert response.headers["location"] == "/book/3"


def test_invalid_registration_shows_field_messages_and_keeps_what_was_typed(client, mailbox):
    response = _ask_register(client, email="bobur@example", full_name="   ")

    assert response.status_code == 422
    html = response.text
    assert "Enter your name, so the business knows who is coming." in html
    assert "Enter an email address like name@example.com." in html
    assert 'value="bobur@example"' in html
    assert 'aria-invalid="true"' in html
    assert mailbox.sent == []
    assert "password" not in html.lower().replace("no password", "")


def test_signing_up_with_a_taken_email_looks_the_same_and_sends_a_sign_in_code(
    client, aziza, mailbox
):
    """No "already registered" page exists to probe."""
    response = _ask_register(client, email="AZIZA@example.com", full_name="Someone Else")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login/code?")
    assert "Hello Aziza Karimova," in mailbox.to("aziza@example.com")[0].body


def test_register_without_a_csrf_token_is_a_403_page(client, mailbox):
    response = client.post("/register", data={"full_name": "Bobur", "email": "bobur@example.com"})

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("text/html")
    assert "This form has expired" in response.text
    assert mailbox.sent == []


def test_a_mail_server_that_is_down_says_so_and_keeps_the_form(client, mailbox):
    mailbox.fail = True

    response = _ask_register(client)

    assert response.status_code == 503
    assert "We could not send the email." in response.text
    assert 'value="bobur@example.com"' in response.text


# --- Sign in ------------------------------------------------------------------------


def test_login_emails_a_code_and_opens_the_code_page(client, aziza, mailbox):
    response = _ask_login(client)

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login/code?")
    assert len(mailbox.to("aziza@example.com")) == 1


def test_an_unknown_email_is_told_so_in_red_under_the_field_and_gets_no_email(client, mailbox):
    response = _ask_login(client, "nobody@example.com")

    assert response.status_code == 422
    assert 'class="field__error"' in response.text
    assert "No account with this email address." in response.text
    assert 'value="nobody@example.com"' in response.text  # what was typed is kept
    assert mailbox.sent == []


def test_a_deactivated_account_is_told_so_and_gets_no_email(client, db, mailbox):
    add_barber(db, "off@example.com", "Off").is_active = False
    db.flush()

    response = _ask_login(client, "off@example.com")

    assert response.status_code == 401
    assert "This account has been deactivated." in response.text
    assert mailbox.sent == []


def test_the_code_page_says_where_the_code_went_without_confirming_an_account(client, aziza):
    html = client.get("/login/code", params={"email": "aziza@example.com"}).text

    assert "If <strong>aziza@example.com</strong> can sign in" in html
    assert 'autocomplete="one-time-code"' in html
    assert 'inputmode="numeric"' in html
    assert 'action="/login/code"' in html


def test_the_code_page_without_an_email_goes_back_to_login(client):
    response = client.get("/login/code", follow_redirects=False)

    assert (response.status_code, response.headers["location"]) == (303, "/login")


def test_the_code_page_resends_a_sign_in_to_login_and_a_sign_up_to_register(client):
    sign_in = client.get("/login/code", params={"email": "a@example.com"}).text
    sign_up = client.get("/login/code", params={"email": "a@example.com", "name": "Aziza K"}).text

    assert 'action="/login"' in sign_in and 'action="/register"' in sign_up
    assert 'name="full_name" value="Aziza K"' in sign_up
    assert "Send a new code" in sign_in and "Send a new code" in sign_up


def test_the_code_page_tells_a_developer_where_the_code_is_when_no_mail_server_is_set(client):
    assert (
        "the code is in the app's log"
        in client.get("/login/code", params={"email": "a@example.com"}).text
    )


def test_login_signs_in_and_redirects_home_with_a_notice(client, aziza, mailbox):
    response = _login(client, mailbox)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert ACCESS_COOKIE in response.cookies
    assert "You&#39;re signed in." in client.get("/").text


def test_login_rotates_the_csrf_token(client, aziza, mailbox):
    before = _csrf(client)

    _login(client, mailbox)

    assert client.cookies[CSRF_COOKIE] != before


def test_a_wrong_code_shows_the_error_and_keeps_the_email(client, aziza, mailbox):
    _ask_login(client)
    code = mailbox.last_code("aziza@example.com")

    response = _enter_code(client, "000000" if code != "000000" else "111111")

    assert response.status_code == 401
    assert "That code is wrong or has expired." in response.text
    assert 'name="email" value="aziza@example.com"' in response.text
    assert ACCESS_COOKIE not in response.cookies


def test_a_code_that_is_not_six_digits_asks_for_six(client, aziza):
    response = _enter_code(client, "12ab")

    assert response.status_code == 422
    assert "Enter the 6-digit code from the email." in response.text


def test_the_code_with_a_space_in_it_is_accepted(client, aziza, mailbox):
    _ask_login(client)
    code = mailbox.last_code("aziza@example.com")

    assert _enter_code(client, f"{code[:3]} {code[3:]}").status_code == 303


def test_empty_login_form_asks_for_the_email(client, mailbox):
    response = _ask_login(client, "")

    assert response.status_code == 422
    assert "Enter an email address like name@example.com." in response.text
    assert mailbox.sent == []


def test_login_without_a_csrf_token_is_a_403_page(client, aziza, mailbox):
    """Login CSRF: a form on another site cannot sign a browser in."""
    response = client.post("/login/code", data={"email": "aziza@example.com", "code": "123456"})

    assert response.status_code == 403
    assert "This form has expired" in response.text
    assert ACCESS_COOKIE not in response.cookies


def test_login_goes_on_to_a_same_site_next(client, aziza, mailbox):
    response = _login(client, mailbox, next="/me/bookings?tab=past")

    assert response.headers["location"] == "/me/bookings?tab=past"


@pytest.mark.parametrize(
    "evil", ["https://evil.example", "//evil.example", "/\\evil.example", "/\t/evil.example"]
)
def test_open_redirect_next_is_ignored(client, aziza, mailbox, evil):
    asked = _ask_login(client, next=evil)
    assert "evil.example" not in asked.headers["location"]

    response = _enter_code(client, mailbox.last_code("aziza@example.com"), next=evil)

    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_open_redirect_next_is_not_echoed_into_the_form(client):
    html = client.get("/login", params={"next": "https://evil.example"}).text

    assert "evil.example" not in html
    assert '<input type="hidden" name="next" value="/">' in html


def test_too_many_wrong_codes_are_refused_with_retry_after(client, aziza, mailbox):
    _ask_login(client)
    code = mailbox.last_code("aziza@example.com")
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        _enter_code(client, wrong)

    response = _enter_code(client, code)  # even the right code, while blocked

    assert response.status_code == 429
    assert "Too many wrong codes" in response.text
    assert int(response.headers["retry-after"]) > 0


def test_asking_for_too_many_codes_is_refused_with_retry_after(client, aziza, mailbox):
    for _ in range(5):
        assert _ask_login(client).status_code == 303

    response = _ask_login(client)

    assert response.status_code == 429
    assert "Too many codes were requested" in response.text
    assert int(response.headers["retry-after"]) > 0


def test_signed_in_person_opening_login_register_or_code_page_is_sent_on(client, aziza, mailbox):
    _login(client, mailbox)

    for path in ("/login", "/register", "/login/code?email=a%40example.com"):
        response = client.get(path, params={"next": "/book/3"}, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/book/3"


def test_no_page_asks_for_a_password(client):
    for path in ("/login", "/register", "/login/code?email=a%40example.com"):
        assert 'type="password"' not in client.get(path).text


# --- Log out ---------------------------------------------------------------------


def test_logout_ends_the_session_and_says_so(client, aziza, mailbox):
    _login(client, mailbox)
    token = client.cookies[CSRF_COOKIE]

    response = client.post("/logout", data={"csrf_token": token}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert f'{ACCESS_COOKIE}=""' in response.headers["set-cookie"]
    home = client.get("/").text
    assert "You&#39;re signed out." in home
    assert 'href="/login">Sign in</a>' in home


def test_logout_without_the_csrf_token_is_refused(client, aziza, mailbox):
    """Otherwise any site could sign a visitor out with a hidden form."""
    _login(client, mailbox)

    response = client.post("/logout", follow_redirects=False)

    assert response.status_code == 403
    assert "Sign out" in client.get("/").text  # still signed in


def test_signed_in_header_has_a_confirmed_sign_out_form(client, aziza, mailbox):
    _login(client, mailbox)

    html = client.get("/").text

    assert 'action="/logout"' in html
    assert 'data-confirm="Sign out?"' in html
    assert f'name="csrf_token" value="{client.cookies[CSRF_COOKIE]}"' in html


# --- Pages that need a signed-in person -----------------------------------------------


@pytest.fixture
def client_with_private_page(
    db: Session, frozen_clock: FrozenClock, mailbox: Mailbox
) -> Iterator[TestClient]:
    app = create_app()

    @app.get("/test/private")
    def private(user: CurrentUser):
        return {"id": user.id}

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clock] = lambda: frozen_clock
    app.dependency_overrides[get_mailer] = lambda: mailbox
    limiter = InMemoryLoginLimiter(max_attempts=5, window_seconds=300)
    app.dependency_overrides[get_login_limiter] = lambda: limiter
    with TestClient(app) as test_client:
        yield test_client


def test_a_page_that_needs_sign_in_sends_a_visitor_to_login_and_back(
    client_with_private_page, aziza, mailbox
):
    client = client_with_private_page

    response = client.get("/test/private", params={"x": "1"}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/login?next=%2Ftest%2Fprivate%3Fx%3D1"

    after = _login(client, mailbox, next="/test/private?x=1")
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
    )
    monkeypatch.setattr(web_auth, "get_settings", lambda: settings)


@pytest.fixture
def boss(db: Session) -> User:
    return add_barber(db, "boss@example.com", "Boss")


def test_the_login_page_offers_the_demo_barber_outside_production(client, monkeypatch):
    _demo_settings(monkeypatch)

    html = client.get("/login").text

    assert "/login/demo-barber" in html
    assert "boss@example.com" in html
    assert "no code needed" in html


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
