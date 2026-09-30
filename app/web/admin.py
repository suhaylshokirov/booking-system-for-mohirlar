"""The admin area in the browser. This file: the dashboard and its pending queue.

    GET  /admin                              stats and the pending bookings

The Confirm / Cancel buttons of the queue post to `admin_bookings.py`, which owns
every booking action.

Admin only (`WebAdmin`): a visitor is sent to log in, a customer sees a 404.
"""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.core.pagination import PageParams
from app.services.business_settings import get_business_settings
from app.services.dashboard import get_dashboard
from app.web.deps import WebAdmin
from app.web.templating import render

router = APIRouter(include_in_schema=False)

ClockDep = Annotated[Clock, Depends(get_clock)]

# A business has a handful of providers; the filter lists them all.
ALL_PROVIDERS = PageParams(limit=200, offset=0)


def _render_dashboard(
    request: Request,
    db: DbSession,
    now: datetime,
    *,
    problem: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    context = {
        "business": get_business_settings(db),
        "dashboard": get_dashboard(db, now),
        "problem": problem,
    }
    return render(request, "admin/dashboard.html", context, status_code=status_code)


@router.get("/admin", response_class=HTMLResponse, name="admin_dashboard")
def dashboard(request: Request, db: DbSession, clock: ClockDep, admin: WebAdmin) -> HTMLResponse:
    """Raises: 401 (redirects to log in) for a visitor; 404 for a customer."""
    return _render_dashboard(request, db, clock.now())
