"""`safe_next_path`: after login, only ever redirect within this site."""

import pytest

from app.web.redirects import DEFAULT_NEXT, safe_next_path


@pytest.mark.parametrize(
    "value",
    [
        "/",
        "/book/3",
        "/me/bookings?tab=past",
        "/services/2#providers",
    ],
)
def test_a_path_on_this_site_is_kept(value):
    assert safe_next_path(value) == value


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "https://evil.example/login",
        "http://evil.example",
        "//evil.example",  # protocol-relative: another host
        "///evil.example",
        "/\\evil.example",  # browsers read the backslash as a slash
        "\\\\evil.example",
        "/\t/evil.example",  # browsers strip the tab, leaving //evil.example
        "/\n/evil.example",
        " /book/3",
        "javascript:alert(1)",
        "evil.example",
        "book/3",  # relative: resolves against wherever the form was
    ],
)
def test_anything_that_could_leave_the_site_becomes_the_home_page(value):
    assert safe_next_path(value) == DEFAULT_NEXT
