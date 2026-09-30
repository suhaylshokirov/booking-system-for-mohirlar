"""One error envelope for the whole API.

Every error response under `/api/`, whether we raised it, FastAPI's validation
rejected the input, Starlette couldn't find the route, or something crashed,
has this shape:

    {"error": {"code": "SLOT_TAKEN", "message": "...", "details": {...}}}

Clients can then handle every failure with one code path and switch on `code`.

Everything outside `/api/` is a web page that a person reads in a browser, so
there the same errors become an HTML page instead. This module does not know
how to draw one: the app passes in a `render_page` function (see
`app/web/errors.py`), which keeps `core` free of any template code.
"""

import logging
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

API_PATH_PREFIX = "/api/"

# (request, status code, error code if we raised it, message to show or None
# for the page's own wording)
PageRenderer = Callable[[Request, int, str | None, str | None], Response]

# Codes for errors raised by the framework (`HTTPException`) rather than by us.
# Our own errors pass a specific code to AppError instead.
_HTTP_STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    429: "TOO_MANY_REQUESTS",
}


class AppError(Exception):
    """A business or request error with a stable machine-readable code.

    Services raise subclasses or instances of this; they never build responses.
    `headers` carries things like `Retry-After` on a 429.
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        self.headers = headers


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body = {"error": {"code": code, "message": message, "details": details or {}}}
    return JSONResponse(status_code=status_code, content=body, headers=headers)


def _app_error_json(exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


def _validation_error_json(exc: RequestValidationError) -> JSONResponse:
    # Only loc/msg/type are copied: pydantic's `ctx` can hold objects (such as
    # the original ValueError) that can't be serialised to JSON.
    problems = [
        {
            "field": ".".join(str(part) for part in err["loc"]),
            "message": err["msg"],
            "type": err["type"],
        }
        for err in exc.errors()
    ]
    return error_response(422, "VALIDATION_ERROR", "The request is invalid.", {"errors": problems})


def _http_exception_json(exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
    # Keeps headers the framework sets itself, e.g. `Allow` on a 405.
    return error_response(exc.status_code, code, str(exc.detail), headers=exc.headers)


def register_error_handlers(app: FastAPI, render_page: PageRenderer | None = None) -> None:
    """Install the handlers: JSON envelope for the API, `render_page` for the rest.

    Without `render_page` every path gets JSON.
    """

    def wants_page(request: Request) -> bool:
        return render_page is not None and not request.url.path.startswith(API_PATH_PREFIX)

    async def on_app_error(request: Request, exc: AppError) -> Response:
        if wants_page(request):
            # Our own messages are written for the person using the app, so the
            # page can show them as they are.
            return render_page(request, exc.status_code, exc.code, exc.message)
        return _app_error_json(exc)

    async def on_validation_error(request: Request, exc: RequestValidationError) -> Response:
        if wants_page(request):
            return render_page(request, 422, None, None)
        return _validation_error_json(exc)

    async def on_http_exception(request: Request, exc: StarletteHTTPException) -> Response:
        if wants_page(request):
            # The framework's detail ("Not Found") is terse; the page has better words.
            return render_page(request, exc.status_code, None, None)
        return _http_exception_json(exc)

    async def on_unexpected_error(request: Request, exc: Exception) -> Response:
        # The traceback goes to the log; the client only learns that it was our
        # fault, so internals (SQL, paths) never leak.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        if wants_page(request):
            return render_page(request, 500, None, None)
        return error_response(500, "INTERNAL_ERROR", "Something went wrong on our side.")

    app.add_exception_handler(AppError, on_app_error)
    app.add_exception_handler(RequestValidationError, on_validation_error)
    app.add_exception_handler(StarletteHTTPException, on_http_exception)
    app.add_exception_handler(Exception, on_unexpected_error)
