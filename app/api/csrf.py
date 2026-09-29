"""CSRF protection: double-submit cookie.

The attack: a malicious site makes the victim's browser send a request to us,
and the browser attaches the victim's login cookie. Defence: state-changing
requests must also carry a secret only our own pages can read.

How: login sets a random `csrf_token` cookie. Our pages read it and echo it back
in an `X-CSRF-Token` header (JavaScript) or a `csrf_token` form field (plain
HTML forms). A cross-site page can make the browser *send* the cookie but cannot
*read* it, so it cannot produce the matching copy.

Two dependencies:
- `csrf_protect`, installed on the whole app, checks every unsafe request that
  is authenticated by the login cookie. Bearer requests are exempt: browsers
  never attach an `Authorization` header by themselves, so a forged cross-site
  request cannot carry one. Because it is global, a new endpoint cannot forget it.
- `require_csrf` always checks. For HTML forms posted before login (login,
  register), where there is no login cookie yet; use with `ensure_csrf_cookie`.

Errors raised: 403 `CSRF_FAILED`.
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials

from app.api.cookies import ACCESS_COOKIE, CSRF_COOKIE
from app.api.deps import bearer_scheme
from app.core.errors import AppError
from app.core.security import csrf_tokens_match

CSRF_HEADER = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_FORM_TYPES = ("application/x-www-form-urlencoded", "multipart/form-data")


async def _submitted_token(request: Request) -> str | None:
    """The token the client sent: the header, else the form field."""
    header = request.headers.get(CSRF_HEADER)
    if header:
        return header
    content_type = request.headers.get("content-type", "")
    if content_type.startswith(_FORM_TYPES):
        # Starlette caches the parsed form, so the endpoint's own `Form(...)`
        # parameters still work after this.
        field = (await request.form()).get(CSRF_FORM_FIELD)
        return field if isinstance(field, str) else None
    return None


async def _verify(request: Request) -> None:
    if not csrf_tokens_match(request.cookies.get(CSRF_COOKIE), await _submitted_token(request)):
        raise AppError(
            "CSRF_FAILED",
            f"Missing or invalid CSRF token. Send the csrf_token cookie's value in the "
            f"{CSRF_HEADER} header (or a {CSRF_FORM_FIELD} form field), "
            "or authenticate with a Bearer token instead.",
            status_code=403,
        )


async def csrf_protect(
    request: Request,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> None:
    """Global check: unsafe requests authenticated by the login cookie need a token."""
    if request.method in _SAFE_METHODS:
        return
    if bearer is not None:
        return  # get_current_user will authenticate by the header, not the cookie
    if ACCESS_COOKIE not in request.cookies:
        return  # nothing for a forged request to ride on
    await _verify(request)


async def require_csrf(request: Request) -> None:
    """Always check, for forms posted while logged out."""
    await _verify(request)
