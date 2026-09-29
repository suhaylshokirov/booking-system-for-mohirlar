"""/auth: register, log in, log out, who am I."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.cookies import clear_login_cookies, set_access_cookie, set_csrf_cookie
from app.api.deps import CurrentUser, get_login_limiter
from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.core.rate_limit import LoginAttemptLimiter
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.schemas.errors import ErrorResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer account",
    responses={
        409: {
            "model": ErrorResponse,
            "description": "`EMAIL_TAKEN`: the email is already registered (any letter case).",
        }
    },
)
def register(body: RegisterRequest, db: DbSession) -> UserResponse:
    """Always creates a `customer`; there is no way to ask for another role.

    The email is trimmed and lower-cased before it is stored or compared.
    """
    user = auth_service.register_customer(
        db, email=body.email, password=body.password, full_name=body.full_name
    )
    return UserResponse.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in",
    responses={
        401: {
            "model": ErrorResponse,
            "description": (
                "`INVALID_CREDENTIALS` (unknown email and wrong password look identical) "
                "or `ACCOUNT_INACTIVE`."
            ),
        },
        429: {
            "model": ErrorResponse,
            "description": (
                "`TOO_MANY_ATTEMPTS`: too many failed logins for this IP and email. "
                "Wait `Retry-After` seconds."
            ),
        },
    },
)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    limiter: Annotated[LoginAttemptLimiter, Depends(get_login_limiter)],
) -> TokenResponse:
    """Sets an HttpOnly login cookie and a readable `csrf_token` cookie for
    browsers, and also returns the token for `Authorization: Bearer` use (curl,
    Swagger's Authorize button)."""
    now = clock.now()
    user = auth_service.login(
        db,
        limiter,
        email=body.email,
        password=body.password,
        client_ip=request.client.host if request.client else "unknown",
        now=now,
    )
    token = create_access_token(user.id, now)
    set_access_cookie(response, token)
    # A new CSRF token per login, so one issued before login cannot outlive it.
    set_csrf_cookie(response)
    return TokenResponse(access_token=token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out",
    responses={
        403: {
            "model": ErrorResponse,
            "description": "`CSRF_FAILED`, cookie request without the token.",
        }
    },
)
def logout(response: Response) -> None:
    """Clears the login and CSRF cookies. Tokens are stateless, so a copied Bearer
    token stays valid until it expires; logging out ends the browser session.

    When called with the cookie, it needs the CSRF header like any other POST.
    """
    clear_login_cookies(response)


@router.get(
    "/me",
    response_model=UserResponse,
    summary="The logged-in user",
    responses={401: {"model": ErrorResponse, "description": "Not logged in."}},
)
def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
