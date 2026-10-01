"""barbers replace the administrator

The `admin` role becomes `barber`, and every barber is the login of one
provider (`users.provider_id`). Existing admins are carried over: each gets a
provider row of their own, named after them, so the new CHECK (a barber has a
provider, nobody else does) holds for the data that is already there.

`ALTER TYPE ... RENAME VALUE` keeps the enum type and every row that uses it.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE user_role RENAME VALUE 'admin' TO 'barber'")
    op.add_column("users", sa.Column("provider_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        op.f("fk_users_provider_id_providers"),
        "users",
        "providers",
        ["provider_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(op.f("uq_users_provider_id"), "users", ["provider_id"])

    # Give each carried-over admin a provider of their own, before the CHECK.
    connection = op.get_bind()
    for user_id, full_name in connection.execute(
        sa.text("SELECT id, full_name FROM users WHERE role = 'barber'")
    ).all():
        provider_id = connection.execute(
            sa.text("INSERT INTO providers (name) VALUES (:name) RETURNING id"),
            {"name": full_name},
        ).scalar_one()
        connection.execute(
            sa.text("UPDATE users SET provider_id = :provider_id WHERE id = :user_id"),
            {"provider_id": provider_id, "user_id": user_id},
        )

    op.create_check_constraint(
        op.f("ck_users_barber_has_provider"),
        "users",
        "(role = 'barber') = (provider_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_users_barber_has_provider"), "users", type_="check")
    op.drop_constraint(op.f("uq_users_provider_id"), "users", type_="unique")
    op.drop_constraint(op.f("fk_users_provider_id_providers"), "users", type_="foreignkey")
    op.drop_column("users", "provider_id")
    op.execute("ALTER TYPE user_role RENAME VALUE 'barber' TO 'admin'")
