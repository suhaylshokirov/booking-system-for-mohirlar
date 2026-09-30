"""The web UI's foundation: base page, static files, HTML error pages, flash notices."""

from collections.abc import Iterator

import pytest
from fastapi import Response
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.clock import FrozenClock, get_clock
from app.core.db import get_db
from app.core.errors import AppError
from app.main import create_app
from app.web import templating
from app.web.templating import FLASH_COOKIE, Notice, set_flash


@pytest.fixture
def web_client(db: Session, frozen_clock: FrozenClock) -> Iterator[TestClient]:
    """The real app plus probe routes that fail in each way a web page can."""
    app = create_app()
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_clock] = lambda: frozen_clock

    @app.get("/test/gone")
    def gone():
        raise AppError("NOT_FOUND", "This service is no longer offered.", status_code=404)

    @app.get("/test/crash")
    def crash():
        raise RuntimeError("secret internal detail: password=hunter2")

    @app.get("/test/number/{n}")
    def number(n: int):
        return {"n": n}

    # raise_server_exceptions=False so the 500 page is observable.
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _assert_html(response, status: int) -> str:
    assert response.status_code == status
    assert response.headers["content-type"].startswith("text/html")
    return response.text


def test_home_page_renders_inside_the_base_layout(client):
    html = _assert_html(client.get("/"), 200)

    assert "<title>Navbat · Navbat</title>" in html  # default business name, then the product
    assert 'class="brand"' in html
    assert 'id="content"' in html
    assert 'href="#content"' in html  # skip link
    assert 'id="theme-toggle"' in html
    assert 'id="nav-toggle"' in html
    assert 'id="confirm-dialog"' in html
    assert "Asia/Tashkent" in html


def test_home_page_marks_services_as_the_current_nav_item(client):
    html = client.get("/").text

    assert '<a href="/" aria-current="page">Services</a>' in html


def test_page_is_complete_without_javascript(client):
    """No-JS rendering: nothing the page needs is created by the script.

    `has-js` is added by the inline script, so the served markup must not carry
    it; the JS-only toggles are hidden by CSS until that class appears.
    """
    html = client.get("/").text
    css = client.get("/static/css/app.css").text

    assert '<html lang="en">' in html
    assert '<a href="/"' in html  # navigation is plain links
    assert '<script defer src="/static/js/app.js"></script>' in html
    assert "html.has-js .theme-toggle" in css
    assert "html.has-js .nav-toggle" in css


def test_confirm_dialog_focuses_no_first(client):
    html = client.get("/").text

    assert "data-confirm-no autofocus" in html


def test_static_files_are_served(client):
    css = client.get("/static/css/app.css")
    js = client.get("/static/js/app.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "--saffron" in css.text
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
    assert "initConfirmDialog" in js.text


def test_missing_static_file_is_an_html_404(client):
    _assert_html(client.get("/static/css/nope.css"), 404)


def test_unknown_page_is_an_html_404_not_json(client):
    html = _assert_html(client.get("/no-such-page"), 404)

    assert "Page not found" in html
    assert '"error"' not in html


def test_unknown_api_path_is_still_the_json_envelope(client):
    response = client.get("/api/v1/no-such-endpoint")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_app_error_on_a_web_route_shows_its_own_message(web_client):
    html = _assert_html(web_client.get("/test/gone"), 404)

    assert "This service is no longer offered." in html


def test_crash_on_a_web_route_is_an_html_500_without_internals(web_client):
    html = _assert_html(web_client.get("/test/crash"), 500)

    assert "Something broke on our side" in html
    assert "hunter2" not in html


def test_malformed_path_on_a_web_route_is_an_html_page(web_client):
    html = _assert_html(web_client.get("/test/number/abc"), 422)

    assert "Start again from the services" in html


def test_flash_notice_shows_once_and_its_cookie_is_cleared(client, monkeypatch):
    monkeypatch.setitem(templating.FLASH_MESSAGES, "saved", Notice("Saved.", "success"))
    client.cookies.set(FLASH_COOKIE, "saved")

    response = client.get("/")

    assert '<p class="notice notice--success" role="status">Saved.</p>' in response.text
    assert f'{FLASH_COOKIE}=""' in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_unknown_flash_key_shows_nothing(client):
    """The cookie holds a key, not text, so a tampered cookie can't inject wording."""
    client.cookies.set(FLASH_COOKIE, "<script>alert(1)</script>")

    html = client.get("/").text

    assert 'class="notice' not in html
    assert "alert(1)" not in html


def test_set_flash_rejects_an_unknown_key():
    """A typo in a route's flash key fails loudly instead of showing nothing."""
    with pytest.raises(KeyError):
        set_flash(Response(), "no-such-message")
