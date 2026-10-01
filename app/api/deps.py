"""Dependencies shared by the JSON routers: who is calling, and may they?

A caller proves who they are with a Bearer token (API clients, Swagger) or the
HttpOnly cookie set at login (the browser). If both are sent, the Bearer
header wins and is not silently replaced by the cookie when it is bad.

Three levels, used as `CurrentUser`, `OptionalUser` and `AdminUser`:
- `get_current_user`: must be logged in, else 401.
- `get_optional_user`: logged in or anonymous, never fails because of the
  credentials (for public pages that only *adapt* to a logged-in user).
- `require_admin`: logged in *and* an admin, else 401 / 403.
"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.api.cookies import ACCESS_COOKIE
from app.core.clock import Clock, get_clock
from app.core.config import get_settings
from app.core.db import DbSession
from app.core.errors import AppError
from app.core.rate_limit import InMemoryLoginLimiter, LoginAttemptLimiter
from app.core.security import decode_access_token
from app.models.user import User, UserRole
from app.services import auth as auth_service
from app.services.business_settings import get_business_settings

# Shared with the CSRF check so both agree on what counts as a Bearer request.
# auto_error=False: without it a missing header would be a generic 403 before
# we get to look at the cookie. Declaring it also adds "Authorize" to Swagger.
bearer_scheme = HTTPBearer(auto_error=False, description="Token from POST /auth/login.")


def get_current_user(
    request: Request,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
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


def get_optional_user(
    request: Request,
    db: DbSession,
    clock: Annotated[Clock, Depends(get_clock)],
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User | None:
    """The caller if they are properly logged in, otherwise `None`.

    Anything wrong with the credentials (none, expired, tampered, deactivated
    user) counts as anonymous rather than an error: a public page should still
    load for someone whose session expired. Never use this to protect data.
    """
    try:
        return get_current_user(request, db, clock, bearer)
    except AppError as error:
        if error.status_code == 401:
            return None
        raise


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    """The authenticated user, who must be an admin.

    The role is read from the database on this request (not from the token), so
    promoting or demoting someone applies at once.

    Raises:
        AppError: the 401s of `get_current_user`; 403 `FORBIDDEN` for a
            logged-in customer.
    """
    if user.role != UserRole.ADMIN:
        raise AppError("FORBIDDEN", "This action needs an administrator.", status_code=403)
    return user


def is_admin(user: User | None) -> bool:
    """For public endpoints that show admins more (inactive items) than others."""
    return user is not None and user.role == UserRole.ADMIN


def include_inactive_allowed(
    user: Annotated[User | None, Depends(get_optional_user)],
    include_inactive: Annotated[
        bool, Query(description="Admin only: also list deactivated items.")
    ] = False,
) -> bool:
    """Whether this list request may include deactivated items.

    Asking for them without being an admin is refused rather than quietly
    ignored, so a client never mistakes a filtered list for a complete one.

    Raises:
        AppError: 401 `UNAUTHENTICATED` when anonymous; 403 `FORBIDDEN` for a
            customer. Only when `include_inactive=true` was asked for.
    """
    if not include_inactive:
        return False
    if user is None:
        raise AppError("UNAUTHENTICATED", "Log in to continue.", status_code=401)
    if not is_admin(user):
        raise AppError("FORBIDDEN", "This action needs an administrator.", status_code=403)
    return True


@lru_cache
def get_login_limiter() -> LoginAttemptLimiter:
    """The process-wide login limiter. Tests override this with a fresh one."""
    settings = get_settings()
    return InMemoryLoginLimiter(
        settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
    )


def business_timezone(db: DbSession) -> str:
    """The business's IANA timezone, for responses that show local times."""
    return get_business_settings(db).timezone


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
AdminUser = Annotated[User, Depends(require_admin)]
IncludeInactive = Annotated[bool, Depends(include_inactive_allowed)]
BusinessTimezone = Annotated[str, Depends(business_timezone)]
