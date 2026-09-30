"""The two cookies we set, and their attributes in one place.

- `access_token`: the login JWT. HttpOnly, so page scripts (and therefore any
  injected script) cannot read it.
- `csrf_token`: a random value the page reads and echoes back (see
  `app/api/csrf.py`). Deliberately *not* HttpOnly, since reading it is the point.

Both are `SameSite=Lax` (not sent on cross-site POSTs) and `Secure` in
production. Clearing a cookie needs the same attributes it was set with, hence
one helper for both directions.
"""

from fastapi import Request, Response

from app.core.config import get_settings
from app.core.security import generate_csrf_token

ACCESS_COOKIE = "access_token"
CSRF_COOKIE = "csrf_token"


def _attributes() -> dict:
    return {
        "samesite": "lax",
        "secure": get_settings().app_env == "production",  # https only in production
        "path": "/",
    }


def set_access_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        ACCESS_COOKIE,
        token,
        max_age=get_settings().jwt_expire_minutes * 60,
        httponly=True,
        **_attributes(),
    )


def set_csrf_cookie(response: Response, token: str | None = None) -> str:
    """Set the CSRF cookie and return its value (for a hidden form field).

    A fresh token unless `token` is given: an HTML page renders the token into
    its forms before the response exists, then stores that same value here.
    """
    token = token or generate_csrf_token()
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=get_settings().jwt_expire_minutes * 60,
        httponly=False,
        **_attributes(),
    )
    return token


def ensure_csrf_cookie(request: Request, response: Response) -> str:
    """Return the caller's CSRF token, issuing a cookie if they have none.

    For pages with a form that can be posted before login (login, register):
    they need a token too, or an attacker's page could log a victim into the
    attacker's account. An existing cookie is kept so that a second open tab
    does not invalidate the first tab's form.
    """
    return request.cookies.get(CSRF_COOKIE) or set_csrf_cookie(response)


def clear_login_cookies(response: Response) -> None:
    """Remove both cookies. HttpOnly is left off: it does not affect deletion."""
    response.delete_cookie(ACCESS_COOKIE, **_attributes())
    response.delete_cookie(CSRF_COOKIE, **_attributes())
