"""Helpers for the test harness that are worth testing on their own.

`conftest.py` wires them into fixtures; keeping the logic here lets a unit test
call the safety guard directly.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
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


def build_schema(engine: Engine) -> None:
    """Start the test database from an empty schema and migrate it to head.

    Uses the real Alembic migrations, not `create_all`, so the exclusion
    constraints the tests exercise are exactly the ones production gets.
    Until P1.1 adds `alembic.ini` there is nothing to migrate and the schema
    stays empty.
    """
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    if not ALEMBIC_INI.exists():
        return
    config = Config(str(ALEMBIC_INI))
    with engine.begin() as connection:
        # migrations/env.py must use this connection when it is given, so the
        # migration runs against the test database and not DATABASE_URL.
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


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
