"""Dependencies shared by the JSON routers: who is calling?

A caller proves who they are with a Bearer token (API clients, Swagger) or the
HttpOnly cookie set at login (the browser). If both are sent, the Bearer
header wins and is not silently replaced by the cookie when it is bad.
"""

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.clock import Clock, get_clock
from app.core.db import DbSession
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.models.user import User
from app.services import auth as auth_service

ACCESS_COOKIE = "access_token"

# auto_error=False: without it a missing header would be a generic 403 before
# we get to look at the cookie. Declaring it also adds "Authorize" to Swagger.
_bearer = HTTPBearer(auto_error=False, description="Token from POST /auth/login.")


def get_current_user(
    request: Request,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    """The authenticated, active user making this request.

    Raises:
        AppError: 401 `UNAUTHENTICATED` with no credentials; 401
            `INVALID_TOKEN` / `TOKEN_EXPIRED` for a bad token; 401
            `ACCOUNT_INACTIVE` for a deactivated user.
    """
    token = bearer.credentials if bearer else request.cookies.get(ACCESS_COOKIE)
    if not token:
        raise AppError("UNAUTHENTICATED", "Log in to continue.", status_code=401)
    user_id = decode_access_token(token, clock.now())
    return auth_service.get_active_user(db, user_id)


CurrentUser = Annotated[User, Depends(get_current_user)]
