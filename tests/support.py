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
