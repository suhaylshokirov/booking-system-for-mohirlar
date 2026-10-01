"""Accounts: signing up and in with an emailed code, and loading the caller.

There are no passwords (ADR 0013). Signing up and signing in are the same
two steps: ask for a code (`request_registration_code` / `request_login_code`),
then prove it (`verify_code`).

Rules:
- Emails are compared case-insensitively: they are stored trimmed and
  lower-cased, and the unique index on `lower(email)` is the real guarantee.
- A code is 6 digits, lives 10 minutes, works once, and only the newest code
  for an address works (asking again replaces it). After 5 wrong tries the code
  is dead and a new one must be requested.
- Signing up creates a `customer` and only when the code is proven, so an
  address nobody controls never gets an account. Barbers come from the
  create-barber CLI (`ensure_barber`), never from an endpoint.
- Asking for a code answers the same whether or not the address has an account
  (or the account is deactivated): the request endpoints cannot be used to find
  out who is registered. Signing up with an address that already has an account
  just sends it a sign-in code. See `_issue_code` for how the limit stays equal.
- Guessing is limited three ways: per code (5 tries), per (client IP, email) in
  memory, and per email on how many codes may be requested.

Errors raised: `INVALID_CODE` (401), `TOO_MANY_ATTEMPTS` (429, wrong codes),
`TOO_MANY_CODES` (429, codes requested), `EMAIL_SEND_FAILED` (503),
`ACCOUNT_INACTIVE` (401), `INVALID_TOKEN` (401, user no longer exists).
"""

import math
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.core.mail import Mail, Mailer, MailError
from app.core.rate_limit import LoginAttemptLimiter
from app.core.security import generate_login_code, hash_login_code, login_code_matches
from app.models.login_code import LoginCode
from app.models.provider import Provider
from app.models.user import User, UserRole
from app.services.business_settings import get_business_settings

_EMAIL_UNIQUE_INDEX = "uq_users_email_lower"

CODE_LIFETIME = timedelta(minutes=10)
MAX_WRONG_TRIES = 5
# At most this many codes may be requested for one address per window.
MAX_CODES_PER_WINDOW = 5
CODE_WINDOW = timedelta(minutes=10)
# Used-up and expired rows are only history; they are removed after this long.
KEEP_CODES_FOR = timedelta(days=1)


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _find_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(func.lower(User.email) == normalize_email(email)))


def compose_code_mail(
    *, to: str, code: str, name: str | None, business_name: str, lifetime: timedelta
) -> Mail:
    """Pure: the email that carries a code.

    The code is in the subject too, so it can be read from a notification
    without opening the message.
    """
    minutes = int(lifetime.total_seconds() // 60)
    greeting = f"Hello {name}," if name else "Hello,"
    body = (
        f"{greeting}\n\n"
        f"Your sign-in code is {code}\n\n"
        f"It works once and expires in {minutes} minutes. If you did not ask for it, "
        "you can ignore this email: nobody can sign in without the code.\n\n"
        f"{business_name}"
    )
    return Mail(to=to, subject=f"{business_name}: your sign-in code is {code}", body=body)


def _issue_code(
    db: Session,
    mailer: Mailer,
    *,
    email: str,
    full_name: str | None,
    deliver_to: User | None,
    now: datetime,
) -> None:
    """Record a new code for `email` and, if `deliver_to` is given or this is a
    sign-up (`full_name`), email it.

    A row is written even when nothing is sent (an address with no account, or a
    deactivated one). Rows are what the per-address limit counts, so the limit
    trips after the same number of requests for every address; if only real
    accounts were counted, the sixth request would answer 429 for them and 202
    for the rest, and that difference would tell a stranger who has an account.
    The code of such a row is never shown to anyone.

    Raises:
        AppError: 429 `TOO_MANY_CODES` (with `Retry-After`) after too many
            requests for this address; 503 `EMAIL_SEND_FAILED` if the mail
            server refused the message. Then the whole request rolls back: no
            code is left behind that nobody received.
    """
    db.execute(delete(LoginCode).where(LoginCode.created_at < now - KEEP_CODES_FOR))

    since = now - CODE_WINDOW
    recent = list(
        db.scalars(
            select(LoginCode.created_at)
            .where(LoginCode.email == email, LoginCode.created_at > since)
            .order_by(LoginCode.created_at)
        )
    )
    if len(recent) >= MAX_CODES_PER_WINDOW:
        # Free again when the oldest of the counted requests leaves the window.
        wait = max(1, math.ceil((recent[0] + CODE_WINDOW - now).total_seconds()))
        raise AppError(
            "TOO_MANY_CODES",
            f"Too many codes were requested for this email. Try again in {wait} seconds.",
            status_code=429,
            details={"retry_after_seconds": wait},
            headers={"Retry-After": str(wait)},
        )

    # Only the newest code may work: a person who asks twice and types the first
    # one must not be the way in for someone who guessed an older one.
    db.execute(
        update(LoginCode)
        .where(LoginCode.email == email, LoginCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    code = generate_login_code()
    db.add(
        LoginCode(
            email=email,
            code_hash=hash_login_code(email, code),
            full_name=full_name,
            created_at=now,
            expires_at=now + CODE_LIFETIME,
        )
    )
    db.flush()

    if full_name is None and deliver_to is None:
        return  # no (active) account to sign in to: nothing is sent
    mail = compose_code_mail(
        to=email,
        code=code,
        name=full_name or (deliver_to.full_name if deliver_to else None),
        business_name=get_business_settings(db).name,
        lifetime=CODE_LIFETIME,
    )
    try:
        mailer.send(mail)
    except MailError as exc:
        raise AppError(
            "EMAIL_SEND_FAILED",
            "We could not send the email. Please try again in a moment.",
            status_code=503,
        ) from exc


def request_login_code(db: Session, mailer: Mailer, *, email: str, now: datetime) -> None:
    """Email a sign-in code to `email` if it belongs to an active account.

    Returns normally either way (see the module docstring).

    Raises:
        AppError: `TOO_MANY_CODES`, `EMAIL_SEND_FAILED` (see `_issue_code`).
    """
    email = normalize_email(email)
    user = _find_by_email(db, email)
    active = user if user is not None and user.is_active else None
    _issue_code(db, mailer, email=email, full_name=None, deliver_to=active, now=now)


def request_registration_code(
    db: Session, mailer: Mailer, *, email: str, full_name: str, now: datetime
) -> None:
    """Email a code that creates a customer account when it is proven.

    If the address already has an account, it is sent an ordinary sign-in code
    instead (the name typed is ignored), so signing up twice just signs in and
    no "already registered" answer exists to be probed.

    Raises:
        AppError: `TOO_MANY_CODES`, `EMAIL_SEND_FAILED` (see `_issue_code`).
    """
    email = normalize_email(email)
    if _find_by_email(db, email) is not None:
        request_login_code(db, mailer, email=email, now=now)
        return
    _issue_code(db, mailer, email=email, full_name=full_name.strip(), deliver_to=None, now=now)


def verify_code(
    db: Session,
    limiter: LoginAttemptLimiter,
    *,
    email: str,
    code: str,
    client_ip: str,
    now: datetime,
) -> User:
    """Prove a code and return the user it signs in (creating a customer on a sign-up).

    A wrong, expired, used, replaced or never-issued code are all the same
    `INVALID_CODE`, so the answer says nothing about which addresses have codes.
    The limit on wrong guesses is checked first, like a login limit: a blocked
    client cannot learn whether a guess was right.

    A wrong try is written to the database and **committed here**, which is the
    one place a service commits: the caller is about to raise, which rolls the
    request back, and a counter that rolls back with it would count nothing. The
    code is claimed with a guarded `UPDATE ... WHERE consumed_at IS NULL`, so two
    simultaneous requests with the right code cannot both succeed.

    Raises:
        AppError: 429 `TOO_MANY_ATTEMPTS`; 401 `INVALID_CODE`; 401
            `ACCOUNT_INACTIVE` (only after the code was right).
    """
    email = normalize_email(email)
    key = (client_ip, email)
    wait = limiter.retry_after(key, now)
    if wait is not None:
        raise AppError(
            "TOO_MANY_ATTEMPTS",
            f"Too many wrong codes. Try again in {wait} seconds.",
            status_code=429,
            details={"retry_after_seconds": wait},
            headers={"Retry-After": str(wait)},
        )

    live = db.scalar(
        select(LoginCode)
        .where(
            LoginCode.email == email,
            LoginCode.consumed_at.is_(None),
            LoginCode.expires_at > now,  # expired exactly at expires_at
            LoginCode.failed_attempts < MAX_WRONG_TRIES,
        )
        .order_by(LoginCode.created_at.desc(), LoginCode.id.desc())
        .limit(1)
    )
    if live is None or not login_code_matches(email, code, live.code_hash):
        if live is not None:
            db.execute(
                update(LoginCode)
                .where(LoginCode.id == live.id)
                .values(failed_attempts=LoginCode.failed_attempts + 1)
            )
            db.commit()
        limiter.record_failure(key, now)
        raise _invalid_code()

    claimed = db.execute(
        update(LoginCode)
        .where(LoginCode.id == live.id, LoginCode.consumed_at.is_(None))
        .values(consumed_at=now)
    ).rowcount
    if claimed != 1:  # another request used this code a moment ago
        raise _invalid_code()

    user = _find_by_email(db, email)
    if user is None:
        if live.full_name is None:
            raise _invalid_code()  # a sign-in code for an address with no account
        user = _create_customer(db, email=email, full_name=live.full_name)
    if not user.is_active:
        raise AppError("ACCOUNT_INACTIVE", "This account has been deactivated.", status_code=401)
    limiter.reset(key)
    return user


def _invalid_code() -> AppError:
    return AppError(
        "INVALID_CODE",
        "That code is wrong or has expired. Check it, or ask for a new one.",
        status_code=401,
    )


def _create_customer(db: Session, *, email: str, full_name: str) -> User:
    """Insert the customer; if the same address was registered a moment ago by
    another request, use that account (the unique index decides, not a check)."""
    user = User(email=email, full_name=full_name, role=UserRole.CUSTOMER)
    try:
        # A savepoint, so losing the race leaves the caller's session usable.
        with db.begin_nested():
            db.add(user)
            db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig.diag, "constraint_name", None) != _EMAIL_UNIQUE_INDEX:
            raise
        existing = _find_by_email(db, email)
        assert existing is not None  # the index only fires when the row is there
        return existing
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


def demo_sign_in(db: Session, *, email: str) -> User:
    """The user for `email`, with no code: the login page's demo-barber shortcut.

    Only the web route calls this, and only outside production (it answers 404
    there). Never expose it through the API.

    Raises:
        AppError: 401 `INVALID_CODE` if there is no such account (the demo data
            was not seeded); 401 `ACCOUNT_INACTIVE`.
    """
    user = _find_by_email(db, email)
    if user is None:
        raise _invalid_code()
    if not user.is_active:
        raise AppError("ACCOUNT_INACTIVE", "This account has been deactivated.", status_code=401)
    return user


def ensure_barber(db: Session, *, email: str, full_name: str) -> tuple[User, str]:
    """Make sure an active barber with this email exists.

    Idempotent, for the create-barber script. A new email creates the account
    and the barber's provider record (named `full_name`) together: a barber
    without a provider cannot exist (a CHECK on `users` says so). An existing
    account (any letter case, customer or barber) is promoted to barber and
    reactivated; a promoted customer gets a provider too, a barber keeps theirs,
    and nothing is duplicated. Returns the user and what happened: `"created"`,
    `"updated"` or `"unchanged"` (so rerunning the same command changes no row).

    The barber signs in with a code sent to this address, like everyone, so the
    address must be one they can read. Checking that it looks like an email is
    the caller's job (the script validates with the sign-up schema).
    """
    user = _find_by_email(db, email)
    if user is None:
        provider = Provider(name=full_name.strip())
        db.add(provider)
        db.flush()
        user = User(
            email=normalize_email(email),
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
    db.flush()
    return user, "updated" if changed else "unchanged"
