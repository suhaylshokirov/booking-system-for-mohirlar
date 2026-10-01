"""/auth: sign up or in with an emailed code, log out, who am I."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.cookies import clear_login_cookies, set_access_cookie, set_csrf_cookie
from app.api.deps import CurrentUser, get_login_limiter
from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.core.mail import Mailer, get_mailer
from app.core.rate_limit import LoginAttemptLimiter
from app.core.security import create_access_token
from app.schemas.auth import (
    CodeSentResponse,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    VerifyRequest,
)
from app.schemas.errors import ErrorResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


_SENT = CodeSentResponse(
    message="If this address can sign in, a 6-digit code is on its way.",
    expires_in_minutes=int(auth_service.CODE_LIFETIME.total_seconds() // 60),
)

_SEND_ERRORS = {
    429: {
        "model": ErrorResponse,
        "description": (
            "`TOO_MANY_CODES`: too many codes were requested for this email. "
            "Wait `Retry-After` seconds."
        ),
    },
    503: {
        "model": ErrorResponse,
        "description": "`EMAIL_SEND_FAILED`: the mail server did not take the message.",
    },
}


@router.post(
    "/register",
    response_model=CodeSentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sign up: email a code",
    responses=_SEND_ERRORS,
)
def register(
    body: RegisterRequest,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> CodeSentResponse:
    """Step 1 of 2. Sends a 6-digit code to the address. The account is created
    (always a `customer`; there is no way to ask for another role) when the code is
    proven with `POST /auth/verify`.

    If the address already has an account it is sent an ordinary sign-in code
    instead, and the answer is identical, so this endpoint reveals nothing about
    who is registered. The email is trimmed and lower-cased.
    """
    auth_service.request_registration_code(
        db, mailer, email=body.email, full_name=body.full_name, now=clock.now()
    )
    return _SENT


@router.post(
    "/login",
    response_model=CodeSentResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Sign in: email a code",
    responses=_SEND_ERRORS,
)
def login(
    body: LoginRequest,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    mailer: Annotated[Mailer, Depends(get_mailer)],
) -> CodeSentResponse:
    """Step 1 of 2. Sends a 6-digit code if the address has an active account, and
    answers the same if it does not. Prove the code with `POST /auth/verify`."""
    auth_service.request_login_code(db, mailer, email=body.email, now=clock.now())
    return _SENT


@router.post(
    "/verify",
    response_model=TokenResponse,
    summary="Prove the code and sign in",
    responses={
        401: {
            "model": ErrorResponse,
            "description": (
                "`INVALID_CODE` (wrong, expired, already used or replaced: all identical) "
                "or `ACCOUNT_INACTIVE`."
            ),
        },
        429: {
            "model": ErrorResponse,
            "description": (
                "`TOO_MANY_ATTEMPTS`: too many wrong codes for this IP and email. "
                "Wait `Retry-After` seconds."
            ),
        },
    },
)
def verify(
    body: VerifyRequest,
    request: Request,
    response: Response,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    limiter: Annotated[LoginAttemptLimiter, Depends(get_login_limiter)],
) -> TokenResponse:
    """Step 2 of 2. A code works once, for 10 minutes, and dies after 5 wrong tries.

    Sets an HttpOnly login cookie and a readable `csrf_token` cookie for
    browsers, and also returns the token for `Authorization: Bearer` use (curl,
    Swagger's Authorize button). After a sign-up this is also the moment the
    account is created."""
    now = clock.now()
    user = auth_service.verify_code(
        db,
        limiter,
        email=body.email,
        code=body.code,
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
    """The account behind the token or cookie: id, email, name and role (`customer` or
    `barber`). A barber's `provider_id` is the provider they run."""
    return UserResponse.model_validate(user)
