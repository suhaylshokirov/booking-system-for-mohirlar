"""Sign in, create an account, sign out: the browser side of `services/auth`.

Same rules as `/api/v1/auth`: the same schemas validate the input, the same
service functions decide, and the login rate limit applies to both. What
differs is the answer: a page instead of JSON.

- A problem re-renders the form with the message beside the field and the
  email kept (never the password), with the status the API would have used.
- Success sets the login cookie and a fresh CSRF token, leaves a flash notice
  and redirects (303, so a reload doesn't post the form again) to `next`,
  which `safe_next_path` restricts to this site.
- The login and register forms are posted before a login cookie exists, so
  the app-wide CSRF check would skip them; `require_csrf` checks them always
  (login CSRF: an attacker's page signing a victim into the attacker's account).
- Someone already signed in who opens /login or /register is sent on to `next`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import ValidationError

from app.api.cookies import clear_login_cookies, set_access_cookie, set_csrf_cookie
from app.api.csrf import require_csrf
from app.api.deps import get_login_limiter
from app.core.clock import Clock, get_clock
from app.core.config import get_settings
from app.core.db import DbSession
from app.core.errors import AppError
from app.core.rate_limit import LoginAttemptLimiter
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services import auth as auth_service
from app.web.deps import WebUser
from app.web.forms import field_errors
from app.web.redirects import safe_next_path
from app.web.templating import render, set_flash

router = APIRouter(include_in_schema=False)

_EMAIL_MESSAGE = "Enter an email address like name@example.com."

_LOGIN_MESSAGES = {
    "email": _EMAIL_MESSAGE,
    "password": "Enter your password.",
    "password.string_too_long": "That password is longer than any we accept.",
}

_REGISTER_MESSAGES = {
    "email": _EMAIL_MESSAGE,
    "password.string_too_short": "Use at least 8 characters.",
    "password.string_too_long": "Use at most 128 characters.",
    "password": "Choose a password of at least 8 characters.",
    "full_name.string_too_long": "Keep it under 100 characters.",
    "full_name": "Enter your name, so the business knows who is coming.",
}


def _demo_barber() -> dict[str, str] | None:
    """The demo barber's credentials, for the login page's shortcut; `None` in production.

    A convenience for trying the project (owner's decision, see the Deviations
    log): the credentials are the repo's public defaults, so a production
    deployment must never offer them. `demo_barber_login` enforces the same.
    """
    settings = get_settings()
    if settings.app_env == "production":
        return None
    return {"email": settings.barber_email, "password": settings.barber_password}


def _signed_in_redirect(user_id: int, clock: Clock, next_path: str, flash: str) -> Response:
    response = RedirectResponse(next_path, status_code=303)
    set_access_cookie(response, create_access_token(user_id, clock.now()))
    # A new CSRF token per login, so one issued before login cannot outlive it.
    set_csrf_cookie(response)
    set_flash(response, flash)
    return response


@router.get("/login", response_class=HTMLResponse, name="login")
def login_page(request: Request, user: WebUser, next: str | None = None) -> Response:
    next_path = safe_next_path(next)
    if user is not None:
        return RedirectResponse(next_path, status_code=303)
    context = {"next": next_path, "values": {}, "errors": {}, "demo_barber": _demo_barber()}
    return render(request, "auth/login.html", context)


@router.post("/login", dependencies=[Depends(require_csrf)])
def login(
    request: Request,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    limiter: Annotated[LoginAttemptLimiter, Depends(get_login_limiter)],
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
) -> Response:
    next_path = safe_next_path(next)

    def form_again(status_code: int, errors: dict[str, str], problem: str | None = None):
        context = {
            "next": next_path,
            "values": {"email": email},
            "errors": errors,
            "demo_barber": _demo_barber(),
        }
        return render(
            request, "auth/login.html", {**context, "problem": problem}, status_code=status_code
        )

    try:
        body = LoginRequest(email=email, password=password)
    except ValidationError as error:
        return form_again(422, field_errors(error, _LOGIN_MESSAGES))

    try:
        user = auth_service.login(
            db,
            limiter,
            email=body.email,
            password=body.password,
            client_ip=request.client.host if request.client else "unknown",
            now=clock.now(),
        )
    except AppError as error:
        # INVALID_CREDENTIALS, ACCOUNT_INACTIVE or TOO_MANY_ATTEMPTS: the
        # service's message is already written for a person.
        response = form_again(error.status_code, {}, error.message)
        if error.headers:
            response.headers.update(error.headers)  # Retry-After on a 429
        return response

    return _signed_in_redirect(user.id, clock, next_path, "signed_in")


@router.post("/login/demo-barber", dependencies=[Depends(require_csrf)])
def demo_barber_login(
    request: Request,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    limiter: Annotated[LoginAttemptLimiter, Depends(get_login_limiter)],
) -> Response:
    """Sign in as the demo barber and open the barber dashboard: the login page's shortcut button.

    The same `auth_service.login` as the form, with the configured barber
    credentials, so the password check and rate limit still apply.

    Raises: 404 `NOT_FOUND` in production, where the shortcut does not exist. A
    failed login (barber not seeded, password changed) shows the login page again.
    """
    demo = _demo_barber()
    if demo is None:
        raise AppError("NOT_FOUND", "Page not found.", status_code=404)
    try:
        user = auth_service.login(
            db,
            limiter,
            email=demo["email"],
            password=demo["password"],
            client_ip=request.client.host if request.client else "unknown",
            now=clock.now(),
        )
    except AppError as error:
        problem = (
            "The demo barber could not sign in. Run `python -m scripts.seed` "
            "(or `make seed`) to create it."
            if error.code == "INVALID_CREDENTIALS"
            else error.message
        )
        context = {
            "next": "/",
            "values": {},
            "errors": {},
            "demo_barber": demo,
            "problem": problem,
        }
        return render(request, "auth/login.html", context, status_code=error.status_code)
    return _signed_in_redirect(user.id, clock, "/barber", "signed_in")


@router.get("/register", response_class=HTMLResponse, name="register")
def register_page(request: Request, user: WebUser, next: str | None = None) -> Response:
    next_path = safe_next_path(next)
    if user is not None:
        return RedirectResponse(next_path, status_code=303)
    return render(request, "auth/register.html", {"next": next_path, "values": {}, "errors": {}})


@router.post("/register", dependencies=[Depends(require_csrf)])
def register(
    request: Request,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    full_name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    password: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
) -> Response:
    next_path = safe_next_path(next)

    def form_again(status_code: int, errors: dict[str, str], email_taken: bool = False):
        context = {
            "next": next_path,
            "values": {"full_name": full_name, "email": email},
            "errors": errors,
            "email_taken": email_taken,  # offers "Sign in instead"
        }
        return render(request, "auth/register.html", context, status_code=status_code)

    try:
        body = RegisterRequest(email=email, password=password, full_name=full_name)
    except ValidationError as error:
        return form_again(422, field_errors(error, _REGISTER_MESSAGES))

    try:
        user = auth_service.register_customer(
            db, email=body.email, password=body.password, full_name=body.full_name
        )
    except AppError as error:
        if error.code == "EMAIL_TAKEN":
            return form_again(409, {"email": error.message}, email_taken=True)
        raise

    return _signed_in_redirect(user.id, clock, next_path, "registered")


@router.post("/logout")
def logout() -> Response:
    """Ends the browser session. Protected by the app-wide CSRF check, since a
    signed-in browser always carries the login cookie it rides on."""
    response = RedirectResponse("/", status_code=303)
    clear_login_cookies(response)
    set_flash(response, "signed_out")
    return response
