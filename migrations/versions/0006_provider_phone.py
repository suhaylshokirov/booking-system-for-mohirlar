"""a barber's phone number

`providers.phone`, optional, stored in one canonical shape: `+` and 8 to 15
digits, the country code first (E.164), so `tel:` links work from any phone and
two spellings of one number are the same value. The API normalises what a
barber types ("+998 90 123-45-67"); the CHECK is the guarantee.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-01 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("phone", sa.String(length=16), nullable=True))
    op.create_check_constraint(
        op.f("ck_providers_phone_e164"), "providers", "phone ~ '^\\+[1-9][0-9]{7,14}$'"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_providers_phone_e164"), "providers", type_="check")
    op.drop_column("providers", "phone")
