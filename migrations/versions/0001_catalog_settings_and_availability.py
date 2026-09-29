"""catalog, settings and availability tables

First half of the schema: users, business settings, services, providers and
their weekly availability. Bookings and their exclusion constraints follow in
the next migration.

Hand-edited after autogenerate, which cannot see exclusion constraints and does
not drop the `user_role` enum type on downgrade.

Revision ID: 0001
Revises:
Create Date: 2026-09-29 15:34:14.764172
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # btree_gist lets a GiST index / exclusion constraint use plain `=` on
    # integer columns (provider_id, weekday) next to a range `&&` overlap test.
    # Without it Postgres has no GiST operator class for integers.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "business_settings",
        sa.Column("id", sa.Integer(), server_default="1", autoincrement=False, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("timezone", sa.String(length=64), server_default="Asia/Tashkent", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="UZS", nullable=False),
        sa.Column("slot_granularity_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("min_lead_time_minutes", sa.Integer(), server_default="60", nullable=False),
        sa.Column("max_booking_horizon_days", sa.Integer(), server_default="60", nullable=False),
        sa.Column("cancellation_cutoff_hours", sa.Integer(), server_default="2", nullable=False),
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
            "cancellation_cutoff_hours >= 0", name=op.f("ck_business_settings_cutoff_not_negative")
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) > 0", name=op.f("ck_business_settings_name_not_blank")
        ),
        sa.CheckConstraint("id = 1", name=op.f("ck_business_settings_single_row")),
        sa.CheckConstraint(
            "max_booking_horizon_days > 0", name=op.f("ck_business_settings_horizon_positive")
        ),
        sa.CheckConstraint(
            "min_lead_time_minutes >= 0", name=op.f("ck_business_settings_lead_time_not_negative")
        ),
        sa.CheckConstraint(
            "slot_granularity_minutes > 0", name=op.f("ck_business_settings_granularity_positive")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_business_settings")),
    )
    op.create_table(
        "providers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("bio", sa.String(length=1000), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
            "char_length(btrim(name)) > 0", name=op.f("ck_providers_name_not_blank")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_providers")),
    )
    op.create_table(
        "services",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.CheckConstraint("char_length(btrim(name)) > 0", name=op.f("ck_services_name_not_blank")),
        sa.CheckConstraint("duration_minutes > 0", name=op.f("ck_services_duration_positive")),
        sa.CheckConstraint("price >= 0", name=op.f("ck_services_price_not_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_services")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=100), nullable=False),
        sa.Column(
            "role",
            sa.Enum("customer", "admin", name="user_role"),
            server_default="customer",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "uq_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "availability_exceptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=True),
        sa.Column("end_time", sa.Time(), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=True),
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
            "(start_time IS NULL AND end_time IS NULL)"
            " OR (start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time)",
            name=op.f("ck_availability_exceptions_day_off_or_valid_hours"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.id"],
            name=op.f("fk_availability_exceptions_provider_id_providers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_availability_exceptions")),
        sa.UniqueConstraint("provider_id", "date", name="uq_availability_exceptions_provider_date"),
    )
    op.create_table(
        "availability_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("weekday", sa.SmallInteger(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
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
            "end_time > start_time", name=op.f("ck_availability_rules_end_after_start")
        ),
        sa.CheckConstraint(
            "weekday BETWEEN 0 AND 6", name=op.f("ck_availability_rules_weekday_range")
        ),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.id"],
            name=op.f("fk_availability_rules_provider_id_providers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_availability_rules")),
    )
    # Two weekly windows for the same provider on the same weekday must not
    # overlap: they would make the hours ambiguous and generate duplicate slots.
    # `time` has no range type, so both times are pinned to an arbitrary date
    # to build a `tsrange`. The range is half-open, `[)`, so 09:00-13:00 and
    # 13:00-18:00 are adjacent, not overlapping, and are allowed.
    op.execute(
        """
        ALTER TABLE availability_rules
        ADD CONSTRAINT no_availability_rule_overlap
        EXCLUDE USING gist (
            provider_id WITH =,
            weekday WITH =,
            tsrange(
                DATE '2000-01-01' + start_time,
                DATE '2000-01-01' + end_time,
                '[)'
            ) WITH &&
        )
        """
    )
    op.create_table(
        "provider_services",
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("service_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["provider_id"],
            ["providers.id"],
            name=op.f("fk_provider_services_provider_id_providers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"],
            ["services.id"],
            name=op.f("fk_provider_services_service_id_services"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("provider_id", "service_id", name=op.f("pk_provider_services")),
    )


def downgrade() -> None:
    op.drop_table("provider_services")
    # The exclusion constraint goes with its table. btree_gist is left installed:
    # extensions are database-wide and other objects may use them.
    op.drop_table("availability_rules")
    op.drop_table("availability_exceptions")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    # Dropping the table leaves its enum type behind; a later upgrade would fail
    # with "type user_role already exists".
    op.execute("DROP TYPE user_role")
    op.drop_table("services")
    op.drop_table("providers")
    op.drop_table("business_settings")
