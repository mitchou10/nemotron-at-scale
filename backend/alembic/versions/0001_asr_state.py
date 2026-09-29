"""create asr_instances and asr_streams

Revision ID: 0001
Revises:
Create Date: 2026-09-29

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asr_instances",
        sa.Column("key", sa.String(255), primary_key=True),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("priority", sa.Integer, nullable=False),
        sa.Column("max_streams", sa.Integer, nullable=False),
        sa.Column("active_streams", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Float, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "asr_streams",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("client_id", sa.String(255), nullable=False),
        sa.Column("instance", sa.String(255), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failovers", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_asr_streams_client_id", "asr_streams", ["client_id"])
    op.create_index("ix_asr_streams_status", "asr_streams", ["status"])


def downgrade() -> None:
    op.drop_index("ix_asr_streams_status", table_name="asr_streams")
    op.drop_index("ix_asr_streams_client_id", table_name="asr_streams")
    op.drop_table("asr_streams")
    op.drop_table("asr_instances")
