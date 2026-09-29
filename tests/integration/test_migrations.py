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
