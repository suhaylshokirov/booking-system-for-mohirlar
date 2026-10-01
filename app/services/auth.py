"""Accounts: registering, checking credentials, loading the caller.

Rules:
- Emails are compared case-insensitively: they are stored trimmed and
  lower-cased, and the unique index on `lower(email)` is the real guarantee.
- Registration can only ever create a `customer`. Barbers come from the
  create-barber CLI (`ensure_barber`), never from an endpoint.
- A wrong email and a wrong password are indistinguishable to the caller
  (same error, and a password hash is computed either way), so the login
  endpoint cannot be used to find out who has an account.

- Password guessing is rate limited per (client IP, email): after too many
  failures in the window even the correct password is refused until it passes.

Errors raised: `EMAIL_TAKEN` (409), `INVALID_CREDENTIALS` (401),
`ACCOUNT_INACTIVE` (401), `INVALID_TOKEN` (401, user no longer exists),
`TOO_MANY_ATTEMPTS` (429).
"""

from datetime import datetime
from functools import cache

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.rate_limit import LoginAttemptLimiter
from app.core.security import hash_password, verify_password
from app.models.provider import Provider
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


def login(
    db: Session,
    limiter: LoginAttemptLimiter,
    *,
    email: str,
    password: str,
    client_ip: str,
    now: datetime,
) -> User:
    """`authenticate` behind the login rate limit.

    The limit is checked *first*, before any password is verified, so a blocked
    client cannot learn whether a guess was right and the check stays cheap.
    Only wrong credentials count as failures: a correct password on a
    deactivated account is not a guess, and a blocked attempt is not recorded
    (otherwise waiting would never end the block). Success clears the counter.

    Raises:
        AppError: 429 `TOO_MANY_ATTEMPTS` with a `Retry-After` header; plus
            everything `authenticate` raises.
    """
    key = (client_ip, normalize_email(email))
    wait = limiter.retry_after(key, now)
    if wait is not None:
        raise AppError(
            "TOO_MANY_ATTEMPTS",
            f"Too many failed login attempts. Try again in {wait} seconds.",
            status_code=429,
            details={"retry_after_seconds": wait},
            headers={"Retry-After": str(wait)},
        )
    try:
        user = authenticate(db, email=email, password=password)
    except AppError as error:
        if error.code == "INVALID_CREDENTIALS":
            limiter.record_failure(key, now)
        raise
    limiter.reset(key)
    return user


def ensure_barber(db: Session, *, email: str, password: str, full_name: str) -> tuple[User, str]:
    """Make sure an active barber with this email and password exists.

    Idempotent, for the create-barber script. A new email creates the account
    and the barber's provider record (named `full_name`) together: a barber
    without a provider cannot exist (a CHECK on `users` says so). An existing
    account (any letter case, customer or barber) is promoted to barber,
    reactivated and given this password; a promoted customer gets a provider
    too, a barber keeps theirs, and nothing is duplicated. Returns the user and
    what happened: `"created"`, `"updated"` or `"unchanged"` (so rerunning the
    same command changes no row).

    Checking that the email and password are acceptable is the caller's job
    (the script validates with the same schema as registration).
    """
    user = _find_by_email(db, email)
    if user is None:
        provider = Provider(name=full_name.strip())
        db.add(provider)
        db.flush()
        user = User(
            email=normalize_email(email),
            password_hash=hash_password(password),
            full_name=full_name.strip(),
            role=UserRole.BARBER,
            provider_id=provider.id,
        )
        db.add(user)
        db.flush()
        return user, "created"

    changed = False
    if user.provider_id is None:
        provider = Provider(name=user.full_name)
        db.add(provider)
        db.flush()
        user.provider_id, changed = provider.id, True
    if user.role != UserRole.BARBER:
        user.role, changed = UserRole.BARBER, True
    if not user.is_active:
        user.is_active, changed = True, True
    # Compare before hashing: a new salt would "change" the hash on every rerun.
    if not verify_password(password, user.password_hash):
        user.password_hash, changed = hash_password(password), True
    db.flush()
    return user, "updated" if changed else "unchanged"
