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

_Catalog, settings and availability tables (P1.2). `bookings` and
`booking_events` are added in P1.3._

Every table has `created_at` / `updated_at` (see Conventions). Constraint names
below are the real ones; CHECKs and unique indexes are declared on the models in
`app/models/`, exclusion constraints in the migrations.

### `users`
People who log in. `role` is the native enum `user_role` (`customer`, `admin`).
`is_active = false` deactivates an account without deleting the bookings that
reference it. Uniqueness of email is `uq_users_email_lower`, a unique index on
`lower(email)`, so `Ali@x.uz` and `ali@x.uz` are the same address.

### `business_settings`
Exactly one row: `ck_business_settings_single_row` requires `id = 1`, and the
primary key forbids a second row with that id. Holds the display name, IANA
`timezone`, `currency` (UZS), `slot_granularity_minutes`,
`min_lead_time_minutes`, `max_booking_horizon_days` and
`cancellation_cutoff_hours`. Each numeric column has a CHECK (granularity and
horizon > 0; lead time and cutoff >= 0) so a bad edit cannot make slot
generation loop or go negative.

### `services`
What is sold. `duration_minutes` (`ck_services_duration_positive`, > 0) and
`price` (`ck_services_price_not_negative`, >= 0, integer UZS). Names must not be
blank and are capped at 100 characters, descriptions at 1000. Deactivated, not
deleted; bookings copy price and duration (see Snapshot fields).

### `providers`
Staff who perform services. Managed by the admin; they have no login. Soft
deactivation via `is_active`.

### `provider_services`
Which provider offers which service. Composite primary key
`(provider_id, service_id)` makes a duplicate link impossible; both foreign keys
are `ON DELETE RESTRICT`.

### `availability_rules`
Weekly recurring windows in **local wall-clock time** (`time` columns, business
timezone). `weekday` is 0 = Monday … 6 = Sunday (`ck_availability_rules_weekday_range`),
and `ck_availability_rules_end_after_start` requires `end_time > start_time`, so
a window cannot cross midnight. Overlapping windows for the same provider and
weekday are rejected by the exclusion constraint `no_availability_rule_overlap`
(migration `0001`, over a `tsrange` of the two times); adjacent windows
(09:00–13:00 and 13:00–18:00) are allowed.

### `availability_exceptions`
A one-off override for one `date`: both `start_time` and `end_time` NULL means a
day off; both set means custom hours replacing the weekly rules for that date.
`ck_availability_exceptions_day_off_or_valid_hours` rejects one-without-the-other
and `end_time <= start_time`. `uq_availability_exceptions_provider_date` allows
one override per provider per date.

## Constraints and indexes
_Every constraint and index, and **why** it exists._

## The exclusion constraints, in plain language
_How `EXCLUDE USING gist (provider_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&)`
makes double booking impossible, and why only pending/confirmed bookings count._

## Snapshot fields
_Why bookings copy price and duration at booking time._
