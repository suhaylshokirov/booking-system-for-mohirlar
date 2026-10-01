"""Create a barber: a login together with the provider record customers book.

    python -m scripts.create_barber --email jasur@example.com --name Jasur

Without `--email` it uses BARBER_EMAIL from the environment. This is the only
way to get a barber: there is deliberately no endpoint for it, and signing up
always creates a customer (ADR 0010).

There is no password to set (ADR 0013): the barber signs in at /login with the
code emailed to this address, so use an address they can read.

Idempotent: run it again and nothing is duplicated. An existing account with
that email is promoted to barber (and given a provider record if it has none)
and reactivated. The email must pass the same rules as sign-up (a real-looking
address).
"""

import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.db import SessionLocal
from app.schemas.auth import RegisterRequest
from app.services import auth as auth_service

_MESSAGES = {
    "created": "Created barber {email}. They sign in with a code emailed to that address.",
    "updated": "Updated {email}: now an active barber.",
    "unchanged": "{email} is already an active barber. Nothing changed.",
}


def _parse(argv: Sequence[str] | None, settings: Settings) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m scripts.create_barber", description=__doc__)
    parser.add_argument("--email", default=settings.barber_email, help="default: $BARBER_EMAIL")
    parser.add_argument("--name", default="Barber", help="display name for a new account")
    return parser.parse_args(argv)


def validate(email: str, name: str) -> RegisterRequest:
    """The sign-up rules for the email and the name.

    Raises:
        ValueError: with a message fit to print.
    """
    try:
        return RegisterRequest(email=email, full_name=name)
    except ValidationError as error:
        problems = "; ".join(f"{e['loc'][0]}: {e['msg']}" for e in error.errors())
        raise ValueError(f"Invalid barber details: {problems}") from None


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse(argv, get_settings())
    try:
        details = validate(args.email, args.name)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 1

    with SessionLocal() as db:
        user, outcome = auth_service.ensure_barber(
            db, email=details.email, full_name=details.full_name
        )
        db.commit()
    print(_MESSAGES[outcome].format(email=user.email))
    return 0


if __name__ == "__main__":
    sys.exit(main())
