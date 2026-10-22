"""QA review: qa_checked, the criteria QA explicitly checked

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evaluations", sa.Column("qa_checked", JSONB))


def downgrade() -> None:
    op.drop_column("evaluations", "qa_checked")
