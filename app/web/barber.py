"""The barber area in the browser. This file: the dashboard and its pending queue.

It shows the signed-in barber's own bookings and hours (`user.provider_id`).

    GET  /barber                              stats and the pending bookings

The Confirm / Cancel buttons of the queue post to `barber_bookings.py`, which owns
every booking action.

Barber only (`WebBarber`): a visitor is sent to log in, a customer sees a 404.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.models.user import User
from app.services.business_settings import get_business_settings
from app.services.dashboard import get_dashboard
from app.web.deps import WebBarber
from app.web.templating import render

router = APIRouter(include_in_schema=False)

ClockDep = Annotated[Clock, Depends(get_clock)]


def _render_dashboard(
    request: Request,
    db: DbSession,
    barber: User,
    now: datetime,
    *,
    problem: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    context = {
        "business": get_business_settings(db),
        "dashboard": get_dashboard(db, now, barber.provider_id),
        "problem": problem,
    }
    return render(request, "barber/dashboard.html", context, status_code=status_code)


@router.get("/barber", response_class=HTMLResponse, name="barber_dashboard")
def dashboard(request: Request, db: DbSession, clock: ClockDep, barber: WebBarber) -> HTMLResponse:
    """Raises: 401 (redirects to log in) for a visitor; 404 for a customer."""
    return _render_dashboard(request, db, barber, clock.now())
