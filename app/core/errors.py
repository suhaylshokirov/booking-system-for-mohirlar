"""One error envelope for the whole API.

Every error response, whether we raised it, FastAPI's validation rejected the
input, Starlette couldn't find the route, or something crashed, has this shape:

    {"error": {"code": "SLOT_TAKEN", "message": "...", "details": {...}}}

Clients can then handle every failure with one code path and switch on `code`.
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

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


async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
    return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)


async def _handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
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


async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = _HTTP_STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
    # Keeps headers the framework sets itself, e.g. `Allow` on a 405.
    return error_response(exc.status_code, code, str(exc.detail), headers=exc.headers)


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # The traceback goes to the log; the client only learns that it was our fault,
    # so internals (SQL, paths) never leak.
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return error_response(500, "INTERNAL_ERROR", "Something went wrong on our side.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _handle_app_error)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected_error)
