"""Password hashing and access tokens.

Passwords are hashed with Argon2 through pwdlib; the plain password is never
stored or logged.

Access tokens are HS256 JWTs carrying `sub` (the user id), `iat` and `exp`.
The token proves who the caller *was* when it was issued; it says nothing about
role or active status, because those are reloaded from the database on every
request (P2.3) so a deactivation takes effect immediately.

Neither token function reads the system clock: the caller passes `now` (from
`app/core/clock.py`), so tests can issue and expire tokens at exact instants.
That is also why expiry is checked here and not by PyJWT, which would compare
against the real time.

Errors: `decode_access_token` raises `InvalidTokenError` (401) for a token that
is expired, has a bad signature, uses another algorithm (including `alg=none`),
is missing a required claim, or is not a JWT at all.
"""

from datetime import datetime, timedelta

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError

from app.core.config import get_settings
from app.core.errors import AppError

# `recommended()` is Argon2id with the library's current safe parameters.
_hasher = PasswordHash.recommended()

# The only algorithm we sign with, and the only one we accept when decoding.
# Passing this list explicitly is what stops an attacker choosing `alg=none`
# (no signature) or switching to an algorithm we did not intend.
_JWT_ALGORITHM = "HS256"


class InvalidTokenError(AppError):
    """The token cannot be trusted. Always a 401; `code` says why."""

    def __init__(self, code: str = "INVALID_TOKEN", message: str = "The token is invalid.") -> None:
        super().__init__(code, message, status_code=401)


def hash_password(password: str) -> str:
    """Return a salted Argon2 hash of `password`."""
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """True if `password` matches `password_hash`.

    A stored hash in a format we don't recognise counts as a mismatch rather
    than an error, so a bad row can never turn a login attempt into a 500.
    """
    try:
        return _hasher.verify(password, password_hash)
    except UnknownHashError:
        return False


def create_access_token(user_id: int, now: datetime) -> str:
    """Sign a token for `user_id`, valid from `now` for `JWT_EXPIRE_MINUTES`."""
    settings = get_settings()
    claims = {
        # RFC 7519 says `sub` is a string, and PyJWT enforces it on decode.
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str, now: datetime) -> int:
    """Return the user id in `token`, or raise `InvalidTokenError`."""
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret,
            algorithms=[_JWT_ALGORITHM],
            options={
                "require": ["sub", "iat", "exp"],
                # Expiry is checked below against the injected clock.
                "verify_exp": False,
                "verify_iat": False,
            },
        )
        user_id = int(claims["sub"])
        expires_at = datetime.fromtimestamp(claims["exp"], tz=now.tzinfo)
    except (jwt.InvalidTokenError, ValueError, TypeError, OverflowError, OSError):
        # `int()` / `fromtimestamp()` failures mean the claims were the wrong
        # shape (a signed token with `sub: "abc"`), which is still invalid.
        raise InvalidTokenError() from None

    if expires_at <= now:
        raise InvalidTokenError("TOKEN_EXPIRED", "The token has expired. Please log in again.")
    return user_id
