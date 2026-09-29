"""App factory: builds the FastAPI app, registers routers and error handlers."""

from fastapi import Depends, FastAPI

from app.api.csrf import csrf_protect
from app.api.v1 import auth, health, settings
from app.core.errors import register_error_handlers

API_PREFIX = "/api/v1"

DESCRIPTION = """
Navbat is an appointment booking system for a small service business.
Customers pick a service, see free time slots and book one; the business owner
manages services, providers, availability and bookings.

Every error, without exception, has the shape
`{"error": {"code", "message", "details"}}`.
"""

TAGS = [
    {"name": "auth", "description": "Register, log in and out, and who am I."},
    {"name": "settings", "description": "Timezone, currency and booking rules of the business."},
    {"name": "health", "description": "Liveness and database connectivity."},
]


def create_app() -> FastAPI:
    # csrf_protect is app-wide so that no endpoint can forget it (see app/api/csrf.py).
    app = FastAPI(
        title="Navbat",
        description=DESCRIPTION,
        version="0.1.0",
        openapi_tags=TAGS,
        dependencies=[Depends(csrf_protect)],
    )
    register_error_handlers(app)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(settings.router, prefix=API_PREFIX)
    app.include_router(health.router, prefix=API_PREFIX)
    return app


app = create_app()
