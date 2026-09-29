"""Accounts: registering, checking credentials, loading the caller.

Rules:
- Emails are compared case-insensitively: they are stored trimmed and
  lower-cased, and the unique index on `lower(email)` is the real guarantee.
- Registration can only ever create a `customer`. Admins come from the
  create-admin CLI (P2.6), never from an endpoint.
- A wrong email and a wrong password are indistinguishable to the caller
  (same error, and a password hash is computed either way), so the login
  endpoint cannot be used to find out who has an account.

Errors raised: `EMAIL_TAKEN` (409), `INVALID_CREDENTIALS` (401),
`ACCOUNT_INACTIVE` (401), `INVALID_TOKEN` (401, user no longer exists).
"""

from functools import cache

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.models.user import User, UserRole

_EMAIL_UNIQUE_INDEX = "uq_users_email_lower"


def normalize_email(email: str) -> str:
    return email.strip().lower()


@cache
def _dummy_hash() -> str:
    """A valid hash nobody knows the password of, built on first use.

    Checked against when the email is unknown, so "no such user" costs the same
    time as "wrong password" and timing does not reveal which emails exist.
    """
    return hash_password("no-account-has-this-password")


def _find_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))


def _email_taken() -> AppError:
    return AppError("EMAIL_TAKEN", "An account with this email already exists.", status_code=409)


def register_customer(db: Session, *, email: str, password: str, full_name: str) -> User:
    """Create a customer account.

    Raises:
        AppError: 409 `EMAIL_TAKEN` if the email is in use in any letter case.
    """
    email = normalize_email(email)
    # Only for a friendly message. Two simultaneous registrations can both pass
    # this, so the unique index is what actually decides (handled below).
    if _find_by_email(db, email) is not None:
        raise _email_taken()

    user = User(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        role=UserRole.CUSTOMER,  # never taken from the request
    )
    try:
        # A savepoint, so losing the race leaves the caller's session usable.
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig.diag, "constraint_name", None) == _EMAIL_UNIQUE_INDEX:
            raise _email_taken() from exc
        raise
    return user


def authenticate(db: Session, *, email: str, password: str) -> User:
    """Return the user for a correct email + password.

    Raises:
        AppError: 401 `INVALID_CREDENTIALS` for an unknown email or a wrong
            password (identical on purpose); 401 `ACCOUNT_INACTIVE` only after
            the password was correct, so it reveals nothing to a guesser.
    """
    user = _find_by_email(db, email)
    password_ok = verify_password(password, user.password_hash if user else _dummy_hash())
    if user is None or not password_ok:
        raise AppError("INVALID_CREDENTIALS", "Incorrect email or password.", status_code=401)
    if not user.is_active:
        raise AppError("ACCOUNT_INACTIVE", "This account has been deactivated.", status_code=401)
    return user


def get_active_user(db: Session, user_id: int) -> User:
    """Load the user a valid token names, checking they may still act.

    Called on every authenticated request, so deactivating a user takes effect
    at once even though their token has not expired.

    Raises:
        AppError: 401 `INVALID_TOKEN` if the user no longer exists;
            401 `ACCOUNT_INACTIVE` if they were deactivated.
    """
    user = db.get(User, user_id)
    if user is None:
        raise AppError("INVALID_TOKEN", "The token is invalid.", status_code=401)
    if not user.is_active:
        raise AppError("ACCOUNT_INACTIVE", "This account has been deactivated.", status_code=401)
    return user
