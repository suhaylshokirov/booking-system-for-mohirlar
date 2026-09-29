"""Alembic environment: how migrations connect to the database.

Two ways to get a connection:

* The caller passes one in `config.attributes["connection"]`. The test harness
  does this so the migrations run on the *test* database; without it, the
  settings' DATABASE_URL (the development database) would be migrated instead.
* Otherwise the URL comes from the app settings, like the app itself.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool

from app.core.config import get_settings
from app.models import Base

config = context.config
target_metadata = Base.metadata


def _configure_and_run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # Autogenerate also notices column type changes (e.g. int -> bigint).
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """`alembic upgrade head --sql`: print the SQL instead of running it."""
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        # The caller owns this connection (and its logging setup) and decides
        # when to commit; the migration just runs on it.
        _configure_and_run(connection)
        return

    if config.config_file_name is not None:
        # Keep the app's own loggers alive when alembic is run from code.
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    # NullPool: a one-off process should not keep connections open.
    engine = create_engine(get_settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as new_connection:
        _configure_and_run(new_connection)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
