"""QA review: qa_label, qa_overrides, qa_comment, reviewer, reviewed_at

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evaluations", sa.Column("qa_label", sa.String(40)))
    op.add_column("evaluations", sa.Column("qa_overrides", JSONB))
    op.add_column("evaluations", sa.Column("qa_comment", sa.Text))
    op.add_column("evaluations", sa.Column("reviewer", sa.String(200)))
    op.add_column("evaluations", sa.Column("reviewed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    for column in ("reviewed_at", "reviewer", "qa_comment", "qa_overrides", "qa_label"):
        op.drop_column("evaluations", column)
