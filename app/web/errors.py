"""Error pages for the browser: the HTML twin of the API's JSON envelope.

`app/core/errors.py` decides *when* a page is wanted (any path outside
`/api/`); this module decides what the page says. One template serves every
status, with wording chosen here so the template stays formatting only.
"""

from http import HTTPStatus

from fastapi import Request
from fastapi.responses import HTMLResponse

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


def render_error_page(request: Request, status_code: int, message: str | None) -> HTMLResponse:
    """The error page for `status_code`.

    A 500 never shows `message`: it could carry internals. Other statuses show
    our own message when there is one (for example "This service is no longer
    offered."), since it is more specific than the generic wording.
    """
    title, lead = _PAGES.get(status_code, (_reason(status_code), "Go back and try again."))
    if message and status_code != 500:
        lead = message
    context = {"status_code": status_code, "title": title, "lead": lead}
    return render(request, "error.html", context, status_code=status_code)


def _reason(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "Something went wrong"
