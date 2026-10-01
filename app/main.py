"""App factory: builds the FastAPI app, registers routers and error handlers."""

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.csrf import csrf_protect
from app.api.v1 import auth, availability, bookings, health, providers, services, settings, slots
from app.core import openapi
from app.core.errors import register_error_handlers
from app.web import auth as web_auth
from app.web import barber as web_barber
from app.web import barber_availability as web_barber_availability
from app.web import barber_bookings as web_barber_bookings
from app.web import barber_profile as web_barber_profile
from app.web import barber_services as web_barber_services
from app.web import barber_settings as web_barber_settings
from app.web import booking as web_booking
from app.web import catalog
from app.web import my_bookings as web_my_bookings
from app.web.deps import load_current_user
from app.web.errors import render_error_page
from app.web.templating import STATIC_DIR

API_PREFIX = "/api/v1"

DESCRIPTION = """
Navbat is an appointment booking system for a small service business such as a
barbershop. Customers pick a service, see free time slots and book one. The
barbers run the shop: each manages their own bookings, hours and profile, and
any barber manages the services and settings. There is no administrator.

**Try it.** Call `POST /auth/login`, copy `access_token`, press **Authorize** and
paste it. Seeded logins (development): barber `jasur@navbat.local` with
`change-me-barber-password`, customer `demo@navbat.local` with
`demo-customer-password`. A guided curl walkthrough is in `docs/api.md`.

**Who may call what.** Public endpoints need no login; customer endpoints need an
account (`401` without one); barber endpoints need a barber (`403` for a customer);
hours and profile are for the barber who owns them (`403` for another barber's id).
Someone else's booking is `404`, never `403`, so ids cannot be probed.

**Times.** Every instant is ISO 8601 with an offset and is stored in UTC; a time
without an offset is `422`. Responses give the UTC instant (`start_at`) and the
same instant on the business's clock (`local_start`, with its offset).

**Errors.** Every error, without exception, has the shape
`{"error": {"code", "message", "details"}}`. Switch on `code`; the full list is the
"Error codes" table in `docs/api.md`. Lists are paginated with `limit` (1-100, default
20) and `offset`, and return `{items, total, limit, offset}`.
"""

TAGS = [
    {"name": "auth", "description": "Register, log in and out, and who am I."},
    {"name": "settings", "description": "Timezone, currency and booking rules of the business."},
    {"name": "services", "description": "What can be booked: name, duration and price."},
    {"name": "providers", "description": "The staff who perform services, and what each offers."},
    {"name": "availability", "description": "The weekly hours each provider works."},
    {
        "name": "slots",
        "description": "Free times for a service on a day. Public, computed on request.",
    },
    {
        "name": "bookings",
        "description": "Book, look at and cancel your own; barbers confirm, cancel and "
        "complete the bookings made with them. Includes the calendar file.",
    },
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
    openapi.install(app)
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
    app.include_router(catalog.router, dependencies=web)
    app.include_router(web_auth.router, dependencies=web)
    app.include_router(web_booking.router, dependencies=web)
    app.include_router(web_my_bookings.router, dependencies=web)
    app.include_router(web_barber.router, dependencies=web)
    app.include_router(web_barber_services.router, dependencies=web)
    app.include_router(web_barber_profile.router, dependencies=web)
    app.include_router(web_barber_bookings.router, dependencies=web)
    app.include_router(web_barber_settings.router, dependencies=web)
    app.include_router(web_barber_availability.router, dependencies=web)
    return app


app = create_app()
