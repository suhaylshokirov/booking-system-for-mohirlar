"""Finishing touches on the generated OpenAPI document (what Swagger shows).

FastAPI builds most of the document from the routes. Three things are better
said once, here, than repeated on every route:

* **Path parameters.** `{service_id}` and friends get a one-line description.
* **Error examples.** Each documented error response gets an example body whose
  `code` is the first code its description names (`` `SLOT_TAKEN` ``), or the
  usual code for its status, and whose message is the catalog's meaning
  (`error_catalog.ERROR_CATALOG`). Swagger then shows a real envelope for a 409,
  not the same generic one for every status.
* **The 422.** FastAPI documents a 422 as `{"detail": [...]}`, which is not what
  this API sends. It is replaced by the real envelope (`VALIDATION_ERROR`, one
  entry per problem in `details.errors`).
* **A 500 on every operation.** Any endpoint can fail unexpectedly, and the
  error handler answers `INTERNAL_ERROR` in the same envelope, so it is
  documented once for all.

Nothing here changes behaviour; it only edits the document that describes it.
"""

import re
from typing import Any

from fastapi import FastAPI

from app.core.error_catalog import ERROR_CATALOG

PATH_PARAMETERS = {
    "service_id": "Id of the service.",
    "provider_id": "Id of the provider (a barber's public record).",
    "rule_id": "Id of a weekly working window of this provider.",
    "exception_id": "Id of a day-off or custom-hours exception of this provider.",
    "booking_id": "Id of the booking.",
}

# The code to show when a response description names none.
_DEFAULT_CODE = {
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_ATTEMPTS",
    500: "INTERNAL_ERROR",
    503: "DATABASE_UNAVAILABLE",
}

_CODE = re.compile(r"`([A-Z][A-Z_]+)`")


def example_for(status: int, description: str) -> dict[str, Any]:
    """An error body to show for `status`, named after the first catalog code in `description`."""
    code = next(
        (c for c in _CODE.findall(description) if c in ERROR_CATALOG), _DEFAULT_CODE.get(status)
    )
    meaning = ERROR_CATALOG[code][1] if code in ERROR_CATALOG else "Error."
    details: dict[str, Any] = {}
    if code == "VALIDATION_ERROR":
        meaning = "The request is invalid."
        details = {
            "errors": [
                {"field": "body.email", "message": "Field required", "type": "missing"},
            ]
        }
    return {"error": {"code": code, "message": meaning, "details": details}}


def _refs(response: dict[str, Any], name: str) -> bool:
    schema = response.get("content", {}).get("application/json", {}).get("schema", {})
    return schema.get("$ref", "").endswith("/" + name)


def _refs_error_response(response: dict[str, Any]) -> bool:
    return _refs(response, "ErrorResponse")


def document(spec: dict[str, Any]) -> dict[str, Any]:
    """Edit `spec` in place (and return it); see the module docstring."""
    error_schema = {"$ref": "#/components/schemas/ErrorResponse"}
    for operations in spec.get("paths", {}).values():
        for operation in operations.values():
            for parameter in operation.get("parameters", []):
                if parameter["in"] == "path" and not parameter.get("description"):
                    parameter["description"] = PATH_PARAMETERS.get(parameter["name"], "")
            responses = operation["responses"]
            responses.setdefault(
                "500",
                {
                    "description": "`INTERNAL_ERROR`: an unexpected failure on our side.",
                    "content": {"application/json": {"schema": error_schema}},
                },
            )
            framework_422 = responses.get("422")
            if framework_422 and _refs(framework_422, "HTTPValidationError"):
                responses["422"] = {
                    "description": "`VALIDATION_ERROR`: a body, query or path value failed "
                    "validation; see `details.errors`.",
                    "content": {"application/json": {"schema": error_schema}},
                }
            for status, response in responses.items():
                if status.isdigit() and int(status) >= 400 and _refs_error_response(response):
                    content = response["content"]["application/json"]
                    content["example"] = example_for(int(status), response.get("description", ""))
    schemas = spec.get("components", {}).get("schemas", {})
    for unused in ("HTTPValidationError", "ValidationError"):
        if f"/{unused}" not in str(spec["paths"]):
            schemas.pop(unused, None)
    return spec


def install(app: FastAPI) -> None:
    """Make `app.openapi()` return the document with `document()` applied (built once)."""
    build = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            app.openapi_schema = document(build())
        return app.openapi_schema

    app.openapi = openapi  # type: ignore[method-assign]
