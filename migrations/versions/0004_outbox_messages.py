"""outbox messages: notifications written with the booking change

One table, no triggers. The application inserts a row in the same transaction
as the booking change it announces (ADR 0009), so a rolled-back booking leaves
no message behind. Recipient address and text are snapshots.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-01 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "outbox_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=30), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("recipient_user_id", sa.Integer(), nullable=False),
        sa.Column("recipient_email", sa.String(length=254), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "event IN ('booking_created', 'booking_confirmed', 'booking_cancelled')",
            name=op.f("ck_outbox_messages_known_event"),
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
            name=op.f("fk_outbox_messages_booking_id_bookings"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["users.id"],
            name=op.f("fk_outbox_messages_recipient_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outbox_messages")),
    )
    op.create_index("ix_outbox_messages_booking", "outbox_messages", ["booking_id"])
    op.create_index(
        "ix_outbox_messages_unsent",
        "outbox_messages",
        ["id"],
        postgresql_where=sa.text("sent_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_messages_unsent", table_name="outbox_messages")
    op.drop_index("ix_outbox_messages_booking", table_name="outbox_messages")
    op.drop_table("outbox_messages")
