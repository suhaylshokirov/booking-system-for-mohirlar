"""App factory: builds the FastAPI app, registers routers and error handlers."""

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.csrf import csrf_protect
from app.api.v1 import auth, availability, bookings, health, providers, services, settings, slots
from app.core.errors import register_error_handlers
from app.web import auth as web_auth
from app.web import pages
from app.web.deps import load_current_user
from app.web.errors import render_error_page
from app.web.templating import STATIC_DIR

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
    {"name": "services", "description": "What can be booked: name, duration and price."},
    {"name": "providers", "description": "The staff who perform services, and what each offers."},
    {"name": "availability", "description": "The weekly hours each provider works."},
    {"name": "health", "description": "Liveness and database connectivity."},
]


def create_app() -> FastAPI:
    # csrf_protect is app-wide so that no endpoint can forget it (see app/api/csrf.py).
    # That includes the HTML forms of app/web/.
    app = FastAPI(
        title="Navbat",
        description=DESCRIPTION,
        version="0.1.0",
        openapi_tags=TAGS,
        dependencies=[Depends(csrf_protect)],
    )
    # JSON envelope under /api/, an HTML error page everywhere else.
    register_error_handlers(app, render_page=render_error_page)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(settings.router, prefix=API_PREFIX)
    app.include_router(services.router, prefix=API_PREFIX)
    app.include_router(providers.router, prefix=API_PREFIX)
    app.include_router(availability.router, prefix=API_PREFIX)
    app.include_router(slots.router, prefix=API_PREFIX)
    app.include_router(bookings.router, prefix=API_PREFIX)
    app.include_router(health.router, prefix=API_PREFIX)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    # Every page knows who is looking (for the header), attached here so no
    # web router can forget it.
    web = [Depends(load_current_user)]
    app.include_router(pages.router, dependencies=web)
    app.include_router(web_auth.router, dependencies=web)
    return app


app = create_app()
