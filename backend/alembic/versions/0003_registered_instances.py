"""create registered_instances

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "registered_instances",
        sa.Column("id", sa.String(255), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("max_streams", sa.Integer, nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_registered_instances_kind", "registered_instances", ["kind"])
    op.create_index("ix_registered_instances_last_seen", "registered_instances", ["last_seen"])


def downgrade() -> None:
    op.drop_index("ix_registered_instances_last_seen", table_name="registered_instances")
    op.drop_index("ix_registered_instances_kind", table_name="registered_instances")
    op.drop_table("registered_instances")
