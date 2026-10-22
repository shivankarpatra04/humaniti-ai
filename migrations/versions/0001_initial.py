"""tutors and evaluations

Revision ID: 0001
Revises:
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tutors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "evaluations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("cache_key", sa.String(200), nullable=False, unique=True),
        sa.Column("video_sha256", sa.String(64), nullable=False),
        sa.Column("video_path", sa.Text, nullable=False),
        sa.Column("tutor_id", sa.Integer, sa.ForeignKey("tutors.id"), nullable=False),
        sa.Column("batch_id", sa.String(20), nullable=False),
        sa.Column("class_date", sa.Date, nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(100)),
        sa.Column("error", sa.Text),
        sa.Column("label", sa.String(40)),
        sa.Column("rule_applied", sa.Text),
        sa.Column("summary", sa.Text),
        sa.Column("result", JSONB),
        sa.Column("facts", JSONB),
        sa.Column("input_tokens", sa.Integer),
        sa.Column("output_tokens", sa.Integer),
        sa.Column("llm_cost_usd", sa.Float),
        sa.Column("rubric_version", sa.String(40), nullable=False),
        sa.Column("llm_model", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'processing', 'done', 'failed')", name="status_valid"),
    )
    op.create_index("ix_evaluations_video_sha256", "evaluations", ["video_sha256"])
    op.create_index("ix_evaluations_tutor_id_class_date", "evaluations", ["tutor_id", "class_date"])

    # Supabase exposes the public schema through its REST API; RLS with no policies blocks that path,
    # while the backend's postgres role owns the tables and is unaffected.
    op.execute("ALTER TABLE tutors ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE evaluations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE alembic_version ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("evaluations")
    op.drop_table("tutors")
