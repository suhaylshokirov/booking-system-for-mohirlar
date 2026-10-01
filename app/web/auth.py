"""Sign in, sign up, sign out: the browser side of `services/auth`.

Same rules as `/api/v1/auth`: the same schemas validate the input, the same
service functions decide, and the same limits apply. What differs is the
answer: a page instead of JSON. There are no passwords (ADR 0013); signing in
and signing up are two pages each:

1. `/login` (an email) or `/register` (a name and an email) emails a code and
   redirects to `/login/code`.
2. `/login/code` takes the 6 digits. Success sets the login cookie and a fresh
   CSRF token, leaves a flash notice and redirects (303, so a reload doesn't
   post the form again) to `next`, which `safe_next_path` restricts to this site.

- A problem re-renders the form with the message beside the field and the
  input kept, with the status the API would have used.
- The forms are posted before a login cookie exists, so the app-wide CSRF
  check would skip them; `require_csrf` checks them always (login CSRF: an
  attacker's page signing a victim into the attacker's account).
- Someone already signed in who opens these pages is sent on to `next`.
- The email travels in the address of the code page (`?email=`) so a reload or
  the back button keeps working without a session; it is not a secret, and the
  code page proves nothing without the code.
"""

from typing import Annotated
from urllib.parse import urlencode

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
from app.core.mail import Mailer, get_mailer
from app.core.rate_limit import LoginAttemptLimiter
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, RegisterRequest, VerifyRequest
from app.services import auth as auth_service
from app.web.deps import WebUser
from app.web.forms import field_errors
from app.web.redirects import safe_next_path
from app.web.templating import render, set_flash

router = APIRouter(include_in_schema=False)

_EMAIL_MESSAGE = "Enter an email address like name@example.com."

_LOGIN_MESSAGES = {"email": _EMAIL_MESSAGE}

_REGISTER_MESSAGES = {
    "email": _EMAIL_MESSAGE,
    "full_name.string_too_long": "Keep it under 100 characters.",
    "full_name": "Enter your name, so the business knows who is coming.",
}

_CODE_MESSAGES = {"code": "Enter the 6-digit code from the email."}


def _demo_barber() -> dict[str, str] | None:
    """The demo barber's email, for the login page's shortcut; `None` in production.

    A convenience for trying the project without a mail server (owner's decision,
    see the Deviations log): the email is the repo's public default, and the
    shortcut signs in without a code, so a production deployment must never
    offer it. `demo_barber_login` enforces the same.
    """
    settings = get_settings()
    if settings.app_env == "production":
        return None
    return {"email": settings.barber_email}


def _signed_in_redirect(user_id: int, clock: Clock, next_path: str, flash: str) -> Response:
    response = RedirectResponse(next_path, status_code=303)
    set_access_cookie(response, create_access_token(user_id, clock.now()))
    # A new CSRF token per login, so one issued before login cannot outlive it.
    set_csrf_cookie(response)
    set_flash(response, flash)
    return response


def _code_page_redirect(email: str, next_path: str, full_name: str = "") -> Response:
    """To the page that takes the code. `name` is only there so "send a new code"
    on that page can repeat a sign-up instead of a sign-in."""
    query = {"email": email, "next": next_path}
    if full_name:
        query["name"] = full_name
    return RedirectResponse(f"/login/code?{urlencode(query)}", status_code=303)


def _with_retry_after(response: Response, error: AppError) -> Response:
    if error.headers:
        response.headers.update(error.headers)  # Retry-After on a 429
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
    mailer: Annotated[Mailer, Depends(get_mailer)],
    email: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
) -> Response:
    next_path = safe_next_path(next)

    def form_again(status_code: int, errors: dict[str, str], problem: str | None = None):
        context = {
            "next": next_path,
            "values": {"email": email},
            "errors": errors,
            "demo_barber": _demo_barber(),
            "problem": problem,
        }
        return render(request, "auth/login.html", context, status_code=status_code)

    try:
        body = LoginRequest(email=email)
    except ValidationError as error:
        return form_again(422, field_errors(error, _LOGIN_MESSAGES))

    try:
        auth_service.request_login_code(db, mailer, email=body.email, now=clock.now())
    except AppError as error:
        # TOO_MANY_CODES or EMAIL_SEND_FAILED: the message is written for a person.
        return _with_retry_after(form_again(error.status_code, {}, error.message), error)
    return _code_page_redirect(body.email, next_path)


@router.post("/login/demo-barber", dependencies=[Depends(require_csrf)])
def demo_barber_login(request: Request, db: DbSession, clock: Annotated[Clock, Depends(get_clock)]):
    """Sign in as the demo barber and open the barber dashboard: the login page's shortcut button.

    No code is asked for: it exists so the project can be tried without a mail
    server, which is why it is only available outside production.

    Raises: 404 `NOT_FOUND` in production, where the shortcut does not exist. A
    failed sign-in (barber not seeded) shows the login page again.
    """
    demo = _demo_barber()
    if demo is None:
        raise AppError("NOT_FOUND", "Page not found.", status_code=404)
    try:
        user = auth_service.demo_sign_in(db, email=demo["email"])
    except AppError as error:
        problem = (
            "The demo barber could not sign in. Run `python -m scripts.seed` "
            "(or `make seed`) to create it."
            if error.code == "INVALID_CODE"
            else error.message
        )
        context = {"next": "/", "values": {}, "errors": {}, "demo_barber": demo, "problem": problem}
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
    mailer: Annotated[Mailer, Depends(get_mailer)],
    full_name: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
) -> Response:
    next_path = safe_next_path(next)

    def form_again(status_code: int, errors: dict[str, str], problem: str | None = None):
        context = {
            "next": next_path,
            "values": {"full_name": full_name, "email": email},
            "errors": errors,
            "problem": problem,
        }
        return render(request, "auth/register.html", context, status_code=status_code)

    try:
        body = RegisterRequest(email=email, full_name=full_name)
    except ValidationError as error:
        return form_again(422, field_errors(error, _REGISTER_MESSAGES))

    try:
        auth_service.request_registration_code(
            db, mailer, email=body.email, full_name=body.full_name, now=clock.now()
        )
    except AppError as error:
        return _with_retry_after(form_again(error.status_code, {}, error.message), error)
    return _code_page_redirect(body.email, next_path, body.full_name)


def _code_page(*, email: str, next_path: str, name: str, **extra) -> dict:
    return {
        "email": email,
        "next": next_path,
        "name": name,
        "errors": {},
        "problem": None,
        # No mail server configured (development): say where the code went.
        "console_mail": not get_settings().smtp_host,
        **extra,
    }


@router.get("/login/code", response_class=HTMLResponse, name="login_code")
def code_page(
    request: Request,
    user: WebUser,
    email: str = "",
    next: str | None = None,
    name: str = "",
) -> Response:
    next_path = safe_next_path(next)
    if user is not None:
        return RedirectResponse(next_path, status_code=303)
    if not email.strip():
        return RedirectResponse("/login", status_code=303)
    return render(
        request, "auth/code.html", _code_page(email=email, next_path=next_path, name=name)
    )


@router.post("/login/code", dependencies=[Depends(require_csrf)])
def verify_code(
    request: Request,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    limiter: Annotated[LoginAttemptLimiter, Depends(get_login_limiter)],
    email: Annotated[str, Form()] = "",
    code: Annotated[str, Form()] = "",
    next: Annotated[str, Form()] = "",
    name: Annotated[str, Form()] = "",
) -> Response:
    next_path = safe_next_path(next)

    def page_again(status_code: int, errors: dict[str, str], problem: str | None = None):
        context = _code_page(
            email=email, next_path=next_path, name=name, errors=errors, problem=problem
        )
        return render(request, "auth/code.html", context, status_code=status_code)

    try:
        body = VerifyRequest(email=email, code=code)
    except ValidationError as error:
        return page_again(422, field_errors(error, {**_CODE_MESSAGES, "email": _EMAIL_MESSAGE}))

    try:
        user = auth_service.verify_code(
            db,
            limiter,
            email=body.email,
            code=body.code,
            client_ip=request.client.host if request.client else "unknown",
            now=clock.now(),
        )
    except AppError as error:
        # INVALID_CODE, ACCOUNT_INACTIVE or TOO_MANY_ATTEMPTS: the service's
        # message is already written for a person.
        return _with_retry_after(page_again(error.status_code, {}, error.message), error)
    return _signed_in_redirect(user.id, clock, next_path, "signed_in")


@router.post("/logout")
def logout() -> Response:
    """Ends the browser session. Protected by the app-wide CSRF check, since a
    signed-in browser always carries the login cookie it rides on."""
    response = RedirectResponse("/", status_code=303)
    clear_login_cookies(response)
    set_flash(response, "signed_out")
    return response
