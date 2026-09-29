"""SQLAlchemy ORM models — the shape of the database, and nothing else.

Constraints that protect business invariants (exclusion constraints, CHECKs)
are declared in the Alembic migrations, where they are explicit and reviewed;
see docs/database.md.

Every model module must be imported here: Alembic and the test harness read
`Base.metadata`, which only knows the models that have been imported.
"""

from app.models.base import Base, TimestampMixin

__all__ = ["Base", "TimestampMixin"]
