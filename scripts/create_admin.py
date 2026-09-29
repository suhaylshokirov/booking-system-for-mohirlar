"""Create the first admin (or promote / reset an existing account).

    python -m scripts.create_admin --email owner@example.com --password '...'

Without flags it uses ADMIN_EMAIL and ADMIN_PASSWORD from the environment. This
is the only way to get an admin: there is deliberately no endpoint for it, and
registration always creates a customer.

Idempotent: run it again and nothing is duplicated. An existing account with
that email is promoted to admin, reactivated, and given the password. The email
and password must pass the same rules as registration (a real-looking email,
8 to 128 characters). In production the public placeholder password from
`.env.example` is refused as well.

Prefer the ADMIN_PASSWORD environment variable to `--password` on a shared
machine: command-line arguments show up in `ps` and shell history.
"""

import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from app.core.config import PLACEHOLDER_ADMIN_PASSWORD, Settings, get_settings
from app.core.db import SessionLocal
from app.schemas.auth import RegisterRequest
from app.services import auth as auth_service

_MESSAGES = {
    "created": "Created admin {email}.",
    "updated": "Updated {email}: now an active admin with the given password.",
    "unchanged": "{email} is already an active admin with that password. Nothing changed.",
}


def _parse(argv: Sequence[str] | None, settings: Settings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m scripts.create_admin", description=__doc__)
    parser.add_argument("--email", default=settings.admin_email, help="default: $ADMIN_EMAIL")
    parser.add_argument(
        "--password", default=settings.admin_password, help="default: $ADMIN_PASSWORD"
    )
    parser.add_argument("--name", default="Admin", help="display name for a new account")
    return parser.parse_args(argv)


def validate(settings: Settings, email: str, password: str, name: str) -> RegisterRequest:
    """The registration rules, plus no public placeholder password in production.

    Raises:
        ValueError: with a message fit to print.
    """
    if settings.app_env == "production" and password == PLACEHOLDER_ADMIN_PASSWORD:
        raise ValueError("Refusing the placeholder password from .env.example in production.")
    try:
        return RegisterRequest(email=email, password=password, full_name=name)
    except ValidationError as error:
        problems = "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in error.errors())
        raise ValueError(f"Invalid admin details: {problems}") from None


def main(argv: Sequence[str] | None = None) -> int:
    settings = get_settings()
    args = _parse(argv, settings)
    try:
        details = validate(settings, args.email, args.password, args.name)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    with SessionLocal() as db:
        user, outcome = auth_service.ensure_admin(
            db, email=details.email, password=details.password, full_name=details.full_name
        )
        db.commit()
    print(_MESSAGES[outcome].format(email=user.email))
    return 0


if __name__ == "__main__":
    sys.exit(main())
