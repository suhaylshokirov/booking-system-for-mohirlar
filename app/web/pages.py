"""General pages: the home page.

Thin, like every router: read through a service, hand the result to a template.
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.core.db import DbSession
from app.services.business_settings import get_business_settings
from app.web.templating import render

router = APIRouter(include_in_schema=False)


@router.get("/", response_class=HTMLResponse, name="home")
def home(request: Request, db: DbSession) -> HTMLResponse:
    business = get_business_settings(db)
    return render(request, "home.html", {"business": business})
