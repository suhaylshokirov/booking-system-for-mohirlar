# Database

_Skeleton — completed in P1.7 and kept current by every schema change._

## ER diagram
_Mermaid `erDiagram`._

## Conventions

- **Time.** Every timestamp is `timestamptz`, stored and compared in UTC.
  `Base.type_annotation_map` maps every `Mapped[datetime]` to
  `DateTime(timezone=True)`, so a timezone-naive column cannot be declared by
  accident. Local wall-clock times (availability rules) are `time` / `date`
  columns and are converted in one module only (P4.1).
- **`created_at` / `updated_at`.** `TimestampMixin` adds both, set by the
  database clock (`server_default=now()`); `updated_at` is refreshed by
  `onupdate` on every UPDATE SQLAlchemy issues, ORM or Core.
- **Money** is an integer amount in UZS; the currency code lives on business
  settings. No floats, no `Decimal`.
- **Constraint names are predictable.** The naming convention in
  `app/models/base.py` (`pk_`, `fk_`, `uq_`, `ix_`, `ck_` prefixes) gives every
  constraint a stable name, because the API maps a violated constraint to a
  business error *by name* (`no_provider_overlap` → 409 `SLOT_TAKEN`). Every
  `CheckConstraint` must be given a `name=`; the exclusion constraints are named
  explicitly in the migration.
- **Soft deactivation.** Services, providers and users that bookings reference
  are never deleted; they get `is_active = false`. Foreign keys are
  `ON DELETE RESTRICT`, so the database refuses a hard delete anyway.
- **Migrations are the source of truth for the schema.** They are generated with
  `alembic revision --autogenerate`, then read and edited by hand: autogenerate
  cannot see exclusion constraints. The test harness builds its database with
  the same migrations, and `tests/integration/test_migrations.py` checks every
  migration can be upgraded, downgraded and upgraded again.
- **One transaction per request.** `get_db` (used through `DbSession`) commits
  when the handler returns and rolls back if it raises, so a booking and its
  `booking_events` row are written together or not at all. Services never call
  `commit()`; they call `flush()` when they need a constraint checked at that
  point (which is where the double-booking `23P01` is raised). `DbSession` uses
  `scope="function"` so the commit happens *before* the response is sent: a
  failed commit becomes a 500, never a success response for unsaved data.

## Tables
_One subsection per table: purpose, columns of note._

## Constraints and indexes
_Every constraint and index, and **why** it exists._

## The exclusion constraints, in plain language
_How `EXCLUDE USING gist (provider_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)`
makes double booking impossible, and why only pending/confirmed bookings count._

## Snapshot fields
_Why bookings copy price and duration at booking time._
