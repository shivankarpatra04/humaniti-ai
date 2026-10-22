"""runs_used for the majority vote; tutors matched on name_key, shown as typed

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evaluations", sa.Column("runs_used", sa.Integer))
    op.add_column("tutors", sa.Column("name_key", sa.String(200)))
    op.execute(r"UPDATE tutors SET name_key = lower(regexp_replace(btrim(name), '\s+', ' ', 'g'))")
    op.alter_column("tutors", "name_key", nullable=False)
    op.create_unique_constraint("tutors_name_key_key", "tutors", ["name_key"])
    op.drop_constraint("tutors_name_key", "tutors")


def downgrade() -> None:
    op.create_unique_constraint("tutors_name_key", "tutors", ["name"])
    op.drop_constraint("tutors_name_key_key", "tutors")
    op.drop_column("tutors", "name_key")
    op.drop_column("evaluations", "runs_used")
