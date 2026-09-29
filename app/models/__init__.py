"""SQLAlchemy ORM models — the shape of the database, and nothing else.

Constraints that protect business invariants (exclusion constraints, CHECKs)
are declared in the Alembic migrations, where they are explicit and reviewed;
see docs/database.md.
"""
