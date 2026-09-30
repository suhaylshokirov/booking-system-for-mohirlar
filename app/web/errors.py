"""Error pages for the browser: the HTML twin of the API's JSON envelope.

`app/core/errors.py` decides *when* a page is wanted (any path outside
`/api/`); this module decides what the page says. One template serves every
status, with wording chosen here so the template stays formatting only.

One status is not a page at all: a 401 on a GET means "sign in first", so the
browser is sent to the login page and brought back afterwards.
"""

from http import HTTPStatus
from urllib.parse import urlencode

from fastapi import Request, Response
from fastapi.responses import RedirectResponse

from app.web.templating import render

# status -> (title, what to do next). Statuses not listed fall back to the
# standard reason phrase and the message the error carried.
_PAGES: dict[int, tuple[str, str]] = {
    404: (
        "Page not found",
        "Nothing lives at this address. The link may be out of date, or the address mistyped.",
    ),
    422: (
        "That link isn't valid",
        "Part of the address isn't in the form this page expects. Start again from the services.",
    ),
    500: (
        "Something broke on our side",
        "It's been logged. Nothing you did caused it. Try again in a moment.",
    ),
}

# Error codes whose API message is written for developers, not for a page.
_CODE_PAGES: dict[str, tuple[str, str]] = {
    # Usually a form left open for a long time, or cookies cleared in between.
    "CSRF_FAILED": (
        "This form has expired",
        "Go back, reload the page and send the form again. The check protects "
        "your account from forms on other websites.",
    ),
}


def render_error_page(
    request: Request, status_code: int, code: str | None, message: str | None
) -> Response:
    """The error page for `status_code` (or a redirect to log in, for a 401 GET).

    A 500 never shows `message`: it could carry internals. Other statuses show
    our own message when there is one (for example "This service is no longer
    offered."), since it is more specific than the generic wording.
    """
    if status_code == 401 and request.method == "GET":
        return _redirect_to_login(request)
    if code in _CODE_PAGES:
        title, lead = _CODE_PAGES[code]
    else:
        title, lead = _PAGES.get(status_code, (_reason(status_code), "Go back and try again."))
        if message and status_code != 500:
            lead = message
    context = {"status_code": status_code, "title": title, "lead": lead}
    return render(request, "error.html", context, status_code=status_code)


def _redirect_to_login(request: Request) -> RedirectResponse:
    here = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return RedirectResponse(f"/login?{urlencode({'next': here})}", status_code=303)


def _reason(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Something went wrong"
