"""Helpers for the test harness that are worth testing on their own.

`conftest.py` wires them into fixtures; keeping the logic here lets a unit test
call the safety guard directly.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url

from app.core.config import Settings

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def ensure_test_database_is_separate(settings: Settings) -> None:
    """Refuse to run when the tests would use the development database.

    The harness drops and recreates the whole schema of the test database, so
    pointing it at the development database would wipe real data. Compared by
    host, port and database name rather than by string, so a spelling
    difference in the URL cannot slip past.

    Raises:
        RuntimeError: TEST_DATABASE_URL and DATABASE_URL name the same database.
    """
    test = make_url(settings.test_database_url)
    dev = make_url(settings.database_url)
    if (test.host, test.port or 5432, test.database) == (dev.host, dev.port or 5432, dev.database):
        raise RuntimeError(
            "TEST_DATABASE_URL and DATABASE_URL point at the same database "
            f"({test.database!r} on {test.host}). The tests reset their database, "
            "so they refuse to run. Give TEST_DATABASE_URL its own database."
        )


def alembic_config(connection: Connection | None = None) -> Config:
    """Alembic config for the repo's migrations.

    With a `connection`, `migrations/env.py` runs on it instead of opening one
    from DATABASE_URL, so the migration lands in the test database and inside
    whatever transaction the caller holds.
    """
    config = Config(str(ALEMBIC_INI))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def build_schema(engine: Engine) -> None:
    """Start the test database from an empty schema and migrate it to head.

    Uses the real Alembic migrations, not `create_all`, so the exclusion
    constraints the tests exercise are exactly the ones production gets.
    """
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "head")


def truncate_all_tables(engine: Engine) -> None:
    """Empty every table except Alembic's bookkeeping table."""
    with engine.begin() as connection:
        tables = (
            connection.execute(
                text(
                    "SELECT quote_ident(tablename) FROM pg_tables "
                    "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
                )
            )
            .scalars()
            .all()
        )
        if tables:
            connection.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))


def add_barber(db, email: str = "boss@example.com", name: str = "Boss", provider=None):
    """A barber user and the provider they run (made here unless one is given).

    Flushed, not committed. The database refuses a barber without a provider, so
    tests that need a barber go through here instead of building a `User` by hand.
    """
    from app.models import Provider, User, UserRole

    if provider is None:
        provider = Provider(name=name)
        db.add(provider)
        db.flush()
    user = User(
        email=email,
        full_name=name,
        role=UserRole.BARBER,
        provider_id=provider.id,
    )
    db.add(user)
    db.flush()
    return user


def bearer(user, clock) -> dict[str, str]:
    """Bearer headers for an existing `user` (no CSRF needed)."""
    from app.core.security import create_access_token

    return {"Authorization": f"Bearer {create_access_token(user.id, clock.now())}"}


class Mailbox:
    """A mailer that keeps what it was asked to send, for tests to read.

    `fail` makes the next sends raise `MailError`, like a mail server that is down.
    """

    def __init__(self) -> None:
        from app.core.mail import Mail

        self.sent: list[Mail] = []
        self.fail = False

    def send(self, mail) -> None:
        from app.core.mail import MailError

        if self.fail:
            raise MailError("The email could not be sent.")
        self.sent.append(mail)

    def to(self, email: str) -> list:
        return [mail for mail in self.sent if mail.to == email]

    def last_code(self, email: str) -> str:
        """The 6 digits in the newest email sent to `email`."""
        import re

        mails = self.to(email)
        assert mails, f"no email was sent to {email}"
        return re.search(r"sign-in code is (\d{6})", mails[-1].body).group(1)


API_AUTH = "/api/v1/auth"


def api_sign_up(client, mailbox, email="aziza@example.com", full_name="Aziza Karimova"):
    """Sign up through the API: request the code, read it from the mailbox, prove it.

    Returns the `/auth/verify` response. The client's cookie jar then holds the
    login and CSRF cookies.
    """
    sent = client.post(f"{API_AUTH}/register", json={"email": email, "full_name": full_name})
    assert sent.status_code == 202, sent.text
    return client.post(
        f"{API_AUTH}/verify",
        json={"email": email, "code": mailbox.last_code(email.strip().lower())},
    )


def api_sign_in(client, mailbox, email="aziza@example.com"):
    """Sign in through the API with the code from the mailbox (the account must exist)."""
    sent = client.post(f"{API_AUTH}/login", json={"email": email})
    assert sent.status_code == 202, sent.text
    return client.post(
        f"{API_AUTH}/verify",
        json={"email": email, "code": mailbox.last_code(email.strip().lower())},
    )
