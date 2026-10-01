"""Sign-in codes, access tokens and CSRF tokens.

There are no passwords (ADR 0013). A person proves they own an email address by
typing the 6-digit code sent to it; only a keyed hash of the code is stored.

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

import hmac
import secrets
from datetime import datetime, timedelta

import jwt

from app.core.config import get_settings
from app.core.errors import AppError

LOGIN_CODE_DIGITS = 6

# The only algorithm we sign with, and the only one we accept when decoding.
# Passing this list explicitly is what stops an attacker choosing `alg=none`
# (no signature) or switching to an algorithm we did not intend.
_JWT_ALGORITHM = "HS256"


class InvalidTokenError(AppError):
    """The token cannot be trusted. Always a 401; `code` says why."""

    def __init__(self, code: str = "INVALID_TOKEN", message: str = "The token is invalid.") -> None:
        super().__init__(code, message, status_code=401)


def generate_login_code() -> str:
    """A fresh random 6-digit code, zero-padded ("004217").

    `secrets` is the operating system's random source; `random` is predictable.
    """
    return f"{secrets.randbelow(10**LOGIN_CODE_DIGITS):0{LOGIN_CODE_DIGITS}d}"


def hash_login_code(email: str, code: str) -> str:
    """Keyed hash of a code, bound to the address it was sent to.

    Only this is stored, so a copy of the table does not reveal live codes.
    That is a modest protection (a 6-digit space can be searched, which is what
    the short lifetime and the limit on wrong tries are for), but a code should
    not sit in a database in the clear. The address is part of the input so a
    code is only ever valid for the address it was issued to, and the fixed
    prefix keeps the key (shared with the token signature) from producing a
    value usable anywhere else.
    """
    key = get_settings().jwt_secret.encode()
    return hmac.new(key, f"login-code:{email}:{code}".encode(), "sha256").hexdigest()


def login_code_matches(email: str, code: str, stored_hash: str) -> bool:
    """True if `code` is the code `stored_hash` was made from (constant time)."""
    return hmac.compare_digest(hash_login_code(email, code), stored_hash)


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


def generate_csrf_token() -> str:
    """A fresh unguessable value for the double-submit CSRF cookie."""
    return secrets.token_urlsafe(32)


def csrf_tokens_match(cookie_token: str | None, submitted_token: str | None) -> bool:
    """True if both tokens exist, are non-empty, and are equal.

    Compared in constant time, so response timing cannot be used to guess the
    token one character at a time. An empty or missing value never matches,
    otherwise "no cookie" and "no header" would count as equal.
    """
    if not cookie_token or not submitted_token:
        return False
    # Bytes, because compare_digest raises on a str containing non-ASCII.
    return hmac.compare_digest(cookie_token.encode(), submitted_token.encode())
