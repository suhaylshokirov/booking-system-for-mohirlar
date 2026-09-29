"""booking exclusion constraints: no double booking

The database, not the application, guarantees that nobody is booked twice.
Written by hand: autogenerate cannot see exclusion constraints.

Both constraints:

* compare `tstzrange(start_at, end_at, '[)')`. The range is half-open, so a
  booking that ends at 10:30 and one that starts at 10:30 do not overlap:
  back-to-back appointments are allowed.
* apply only `WHERE status IN ('pending', 'confirmed')`. A cancelled or
  completed booking no longer occupies the time, so it must not block it.
* are checked by Postgres at the moment of the INSERT/UPDATE, under its own
  locking, so two simultaneous transactions cannot both succeed. Violations
  raise SQLSTATE 23P01, which the service layer maps to 409 by constraint name.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-29 16:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Idempotent: 0001 already enabled it, but this migration is the one that
    # depends on it (plain `=` on integer columns inside a GiST constraint), so
    # it says so itself.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # One provider cannot be in two appointments at once -> 409 SLOT_TAKEN.
    op.execute(
        """
        ALTER TABLE bookings
        ADD CONSTRAINT no_provider_overlap
        EXCLUDE USING gist (
            provider_id WITH =,
            tstzrange(start_at, end_at, '[)') WITH &&
        )
        WHERE (status IN ('pending', 'confirmed'))
        """
    )

    # One customer cannot be in two appointments at once, even with different
    # providers -> 409 CUSTOMER_OVERLAP.
    op.execute(
        """
        ALTER TABLE bookings
        ADD CONSTRAINT no_customer_overlap
        EXCLUDE USING gist (
            customer_id WITH =,
            tstzrange(start_at, end_at, '[)') WITH &&
        )
        WHERE (status IN ('pending', 'confirmed'))
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE bookings DROP CONSTRAINT no_customer_overlap")
    op.execute("ALTER TABLE bookings DROP CONSTRAINT no_provider_overlap")
    # btree_gist stays installed: it belongs to the database, and 0001 owns it.
