"""source_url for links, retry_count for the LLM retry rate

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evaluations", sa.Column("source_url", sa.Text))
    op.add_column("evaluations", sa.Column("retry_count", sa.Integer))
    op.create_index("ix_evaluations_source_url", "evaluations", ["source_url"])
    for column in ("cache_key", "video_sha256", "video_path"):
        op.alter_column("evaluations", column, nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM evaluations WHERE cache_key IS NULL OR video_sha256 IS NULL")
    for column in ("cache_key", "video_sha256", "video_path"):
        op.alter_column("evaluations", column, nullable=False)
    op.drop_index("ix_evaluations_source_url", "evaluations")
    op.drop_column("evaluations", "retry_count")
    op.drop_column("evaluations", "source_url")
