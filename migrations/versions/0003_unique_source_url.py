"""one evaluation per link, rubric version and model

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-22
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # the unique constraint's own index replaces the plain one
    op.drop_index("ix_evaluations_source_url", "evaluations")
    op.create_unique_constraint(
        "uq_evaluations_source_url", "evaluations", ["source_url", "rubric_version", "llm_model"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_evaluations_source_url", "evaluations")
    op.create_index("ix_evaluations_source_url", "evaluations", ["source_url"])
