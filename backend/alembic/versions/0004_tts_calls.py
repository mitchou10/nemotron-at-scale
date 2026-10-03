"""create tts_calls

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03

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
        "tts_calls",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("instance", sa.String(255), nullable=True),
        sa.Column("voice", sa.String(255), nullable=True),
        sa.Column("response_format", sa.String(16), nullable=True),
        sa.Column("characters", sa.Integer, nullable=False),
        sa.Column("audio_bytes", sa.Integer, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=False),
        sa.Column("first_byte_ms", sa.Integer, nullable=True),
    )
    op.create_index("ix_tts_calls_at", "tts_calls", ["at"])


def downgrade() -> None:
    op.drop_index("ix_tts_calls_at", table_name="tts_calls")
    op.drop_table("tts_calls")
