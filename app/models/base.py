"""Declarative base, constraint naming convention and the timestamp mixin.

Every model inherits `Base`, so one `MetaData` knows the whole schema and
Alembic can compare it with the database.
"""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable constraint names. The API maps a violated constraint back to a
# business error by its *name* (`no_provider_overlap` -> SLOT_TAKEN), and a name
# Postgres invented (`bookings_check1`) could not be matched. `ck` needs an
# explicit `name=` on every CheckConstraint, which is the point: it cannot be
# forgotten.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    # Every `Mapped[datetime]` becomes `timestamptz`. A timezone-naive column
    # would silently break the "all timestamps are UTC" rule, so it is made
    # impossible to declare by accident.
    type_annotation_map = {datetime: DateTime(timezone=True)}


class TimestampMixin:
    """`created_at` / `updated_at`, both set by the database.

    `now()` is the database clock, so the values are consistent even if several
    app instances have drifting clocks. `onupdate` refreshes `updated_at` on
    every UPDATE that SQLAlchemy issues, ORM or Core.
    """

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
