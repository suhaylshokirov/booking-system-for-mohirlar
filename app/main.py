"""App factory: builds the FastAPI app, registers routers and error handlers."""

from fastapi import FastAPI

from app.api.v1 import health
from app.core.errors import register_error_handlers

API_PREFIX = "/api/v1"

DESCRIPTION = """
Navbat is an appointment booking system for a small service business.
Customers pick a service, see free time slots and book one; the business owner
manages services, providers, availability and bookings.

Every error, without exception, has the shape
`{"error": {"code", "message", "details"}}`.
"""

TAGS = [{"name": "health", "description": "Liveness and database connectivity."}]


def create_app() -> FastAPI:
    app = FastAPI(title="Navbat", description=DESCRIPTION, version="0.1.0", openapi_tags=TAGS)
    register_error_handlers(app)
    app.include_router(health.router, prefix=API_PREFIX)
    return app


app = create_app()
