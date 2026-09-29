"""/auth: register, log in, log out, who am I."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.api.deps import ACCESS_COOKIE, CurrentUser
from app.core.clock import Clock, get_clock
from app.core.config import get_settings
from app.core.db import DbSession
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse
from app.schemas.errors import ErrorResponse
from app.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_settings() -> dict:
    """Attributes for the login cookie. Logout must repeat them to clear it."""
    return {
        "httponly": True,  # page scripts cannot read the token
        "samesite": "lax",  # not sent on cross-site POSTs
        "secure": get_settings().app_env == "production",  # https only in production
        "path": "/",
    }


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
        }
    },
)
def login(
    body: LoginRequest,
    response: Response,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
) -> TokenResponse:
    """Sets an HttpOnly cookie for browsers and also returns the token for
    `Authorization: Bearer` use (curl, Swagger's Authorize button)."""
    user = auth_service.authenticate(db, email=body.email, password=body.password)
    token = create_access_token(user.id, clock.now())
    response.set_cookie(
        ACCESS_COOKIE,
        token,
        max_age=get_settings().jwt_expire_minutes * 60,
        **_cookie_settings(),
    )
    return TokenResponse(access_token=token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out",
)
def logout(response: Response) -> None:
    """Clears the login cookie. Tokens are stateless, so a copied Bearer token
    stays valid until it expires; logging out ends the browser session."""
    response.delete_cookie(ACCESS_COOKIE, **_cookie_settings())


@router.get(
    "/me",
    response_model=UserResponse,
    summary="The logged-in user",
    responses={401: {"model": ErrorResponse, "description": "Not logged in."}},
)
def me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)
