"""Alembic wiring: migrations run on the connection they are given, and every
migration can be undone and redone.

Both tests rewrite the shared test schema, so they rebuild it at the end.
"""

from pathlib import Path
from textwrap import dedent

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.models import Base
from tests.support import alembic_config, build_schema

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "migrations"

ONE_TABLE_MIGRATION = dedent(
    """
    import sqlalchemy as sa
    from alembic import op

    revision = "0001"
    down_revision = None
    branch_labels = None
    depends_on = None


    def upgrade():
        op.create_table("migration_probe", sa.Column("id", sa.Integer, primary_key=True))


    def downgrade():
        op.drop_table("migration_probe")
    """
)


@pytest.fixture
def blank_schema_then_rebuilt(engine):
    """Hand the test an empty schema; put the real one back afterwards."""
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    yield
    build_schema(engine)


def _tables(connection) -> set[str]:
    return set(inspect(connection).get_table_names()) - {"alembic_version"}


def test_env_runs_migrations_on_the_connection_it_is_given(
    engine, blank_schema_then_rebuilt, tmp_path
):
    """The harness depends on this: without it the *development* database
    named by DATABASE_URL would be migrated instead of the test database.

    Uses the real `env.py` with a throwaway one-table migration, so the result
    does not change as real migrations are added.
    """
    scripts = tmp_path / "migrations"
    (scripts / "versions").mkdir(parents=True)
    (scripts / "env.py").write_text((MIGRATIONS_DIR / "env.py").read_text())
    (scripts / "script.py.mako").write_text((MIGRATIONS_DIR / "script.py.mako").read_text())
    (scripts / "versions" / "0001_probe.py").write_text(ONE_TABLE_MIGRATION)
    config = Config()
    config.set_main_option("script_location", str(scripts))

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    with engine.connect() as fresh_connection:
        assert _tables(fresh_connection) == {"migration_probe"}  # committed to the test DB

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    with engine.connect() as fresh_connection:
        assert _tables(fresh_connection) == set()


def test_real_migrations_upgrade_downgrade_upgrade(engine, blank_schema_then_rebuilt):
    """Every migration is reversible, and the migrated schema has exactly the
    tables the models declare (a model without a migration fails here)."""
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "head")
    with engine.connect() as connection:
        assert _tables(connection) == set(Base.metadata.tables)

    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "base")
    with engine.connect() as connection:
        assert _tables(connection) == set()

    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "head")
    with engine.connect() as connection:
        assert _tables(connection) == set(Base.metadata.tables)


def test_migration_0005_turns_an_existing_admin_into_a_barber_with_a_provider(
    engine, blank_schema_then_rebuilt
):
    """Data that already exists must satisfy the new rule (a barber has a provider)."""
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "0004")
        connection.execute(
            text(
                "INSERT INTO users (email, password_hash, full_name, role) VALUES "
                "('boss@example.com', 'x', 'The Boss', 'admin'), "
                "('ali@example.com', 'x', 'Ali', 'customer')"
            )
        )
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "0005")
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT u.role::text, u.full_name, p.name FROM users u "
                "LEFT JOIN providers p ON p.id = u.provider_id ORDER BY u.id"
            )
        ).all()
    assert rows == [("barber", "The Boss", "The Boss"), ("customer", "Ali", None)]

    # And back: the role returns to its old name (the providers stay).
    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "0004")
        roles = connection.execute(text("SELECT role::text FROM users ORDER BY id")).scalars().all()
    assert roles == ["admin", "customer"]


def test_migration_0008_drops_passwords_keeps_users_and_downgrade_restores_the_column(
    engine, blank_schema_then_rebuilt
):
    """Existing accounts survive the move to email codes; only the password hash goes."""
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "0007")
        connection.execute(
            text(
                "INSERT INTO users (email, password_hash, full_name, role) VALUES "
                "('ali@example.com', 'a-hash', 'Ali', 'customer')"
            )
        )
    with engine.begin() as connection:
        command.upgrade(alembic_config(connection), "0008")
    with engine.connect() as connection:
        columns = {c["name"] for c in inspect(connection).get_columns("users")}
        users = connection.execute(text("SELECT email, full_name FROM users")).all()
        assert "password_hash" not in columns
        assert users == [("ali@example.com", "Ali")]
        assert "login_codes" in inspect(connection).get_table_names()

    with engine.begin() as connection:
        command.downgrade(alembic_config(connection), "0007")
        restored = connection.execute(text("SELECT password_hash FROM users")).scalars().all()
        assert restored == [""]  # the column is back; the old hash is gone for good
        assert "login_codes" not in inspect(connection).get_table_names()
