"""email codes replace passwords

Creates `login_codes` (the emailed 6-digit codes, stored as a keyed hash) and
drops `users.password_hash`: nobody has a password any more (ADR 0013).

Downgrade puts the column back, empty. An empty value is not a valid hash, so
the old code treats it as "wrong password" for everyone: the schema is restored,
the passwords are not (they are gone for good once this migration has run).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-01 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "login_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("failed_attempts", sa.SmallInteger(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "failed_attempts >= 0", name=op.f("ck_login_codes_attempts_not_negative")
        ),
        sa.CheckConstraint(
            "expires_at > created_at", name=op.f("ck_login_codes_expires_after_created")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_codes")),
    )
    op.create_index("ix_login_codes_email_created_at", "login_codes", ["email", "created_at"])
    op.drop_column("users", "password_hash")


def downgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_hash", sa.String(length=255), server_default="", nullable=False),
    )
    op.alter_column("users", "password_hash", server_default=None)
    op.drop_index("ix_login_codes_email_created_at", table_name="login_codes")
    op.drop_table("login_codes")
