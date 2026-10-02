"""create asr_samples

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-02

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "asr_samples",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("instance", sa.String(255), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("up", sa.Boolean, nullable=False),
        sa.Column("active_streams", sa.Integer, nullable=False),
        sa.Column("max_streams", sa.Integer, nullable=False),
        sa.Column("latency_ms", sa.Float, nullable=True),
    )
    op.create_index("ix_asr_samples_at", "asr_samples", ["at"])


def downgrade() -> None:
    op.drop_index("ix_asr_samples_at", table_name="asr_samples")
    op.drop_table("asr_samples")
