"""bookings and booking events

Second half of the base schema. The double-booking exclusion constraints are
added by the next migration, so each can be read and explained on its own.

Hand-edited after autogenerate: the shared `booking_status` enum type is
created once, explicitly, and dropped on downgrade.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-29 15:37:39.770781
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# One enum type used by three columns. `create_type=False` stops each column
# from trying to create it again; `upgrade` creates it once, up front.
booking_status = postgresql.ENUM(
    "pending", "confirmed", "cancelled", "completed", name="booking_status", create_type=False
)


def upgrade() -> None:
    booking_status.create(op.get_bind())
    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", booking_status, server_default="pending", nullable=False),
        sa.Column("price_amount", sa.Integer(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("cancelled_by_id", sa.Integer(), nullable=True),
        sa.Column("cancel_reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status = 'cancelled' OR (cancelled_by_id IS NULL AND cancel_reason IS NULL)",
            name=op.f("ck_bookings_cancellation_fields_only_when_cancelled"),
        ),
        sa.CheckConstraint("duration_minutes > 0", name=op.f("ck_bookings_duration_positive")),
        sa.CheckConstraint("end_at > start_at", name=op.f("ck_bookings_end_after_start")),
        sa.CheckConstraint("price_amount >= 0", name=op.f("ck_bookings_price_not_negative")),
        sa.ForeignKeyConstraint(
            ["cancelled_by_id"],
            ["users.id"],
            name=op.f("fk_bookings_cancelled_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["users.id"],
            name=op.f("fk_bookings_customer_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.id"],
            name=op.f("fk_bookings_provider_id_providers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name=op.f("fk_bookings_service_id_services"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_bookings")),
    )
    op.create_index(
        "ix_bookings_customer_start", "bookings", ["customer_id", "start_at"], unique=False
    )
    op.create_index(
        "ix_bookings_provider_start", "bookings", ["provider_id", "start_at"], unique=False
    )
    op.create_index("ix_bookings_status", "bookings", ["status"], unique=False)
    op.create_table(
        "booking_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("booking_id", sa.Integer(), nullable=False),
        sa.Column("from_status", booking_status, nullable=True),
        sa.Column("to_status", booking_status, nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_booking_events_actor_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["booking_id"],
            ["bookings.id"],
            name=op.f("fk_booking_events_booking_id_bookings"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_booking_events")),
    )
    op.create_index(
        "ix_booking_events_booking_created",
        "booking_events",
        ["booking_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_booking_events_booking_created", table_name="booking_events")
    op.drop_table("booking_events")
    op.drop_index("ix_bookings_status", table_name="bookings")
    op.drop_index("ix_bookings_provider_start", table_name="bookings")
    op.drop_index("ix_bookings_customer_start", table_name="bookings")
    op.drop_table("bookings")
    booking_status.drop(op.get_bind())
