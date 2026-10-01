"""a barber's photo, stored in the database

`providers.photo` holds the image bytes and `providers.photo_type` its media
type; both are set or both are NULL. Only the three types the app accepts can
be stored, and the size cap the API applies (2 MB) is repeated here so no other
path can write a larger one. Why the bytes live in Postgres rather than on
disk: ADR 0012.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-01 11:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("providers", sa.Column("photo", sa.LargeBinary(), nullable=True))
    op.add_column("providers", sa.Column("photo_type", sa.String(length=20), nullable=True))
    op.create_check_constraint(
        op.f("ck_providers_photo_with_type"),
        "providers",
        "(photo IS NULL) = (photo_type IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_providers_photo_type_known"),
        "providers",
        "photo_type IN ('image/jpeg', 'image/png', 'image/webp')",
    )
    op.create_check_constraint(
        op.f("ck_providers_photo_size"), "providers", "octet_length(photo) <= 2097152"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_providers_photo_size"), "providers", type_="check")
    op.drop_constraint(op.f("ck_providers_photo_type_known"), "providers", type_="check")
    op.drop_constraint(op.f("ck_providers_photo_with_type"), "providers", type_="check")
    op.drop_column("providers", "photo_type")
    op.drop_column("providers", "photo")
