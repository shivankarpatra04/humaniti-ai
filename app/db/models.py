from datetime import date, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONColumn = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    pass


class Tutor(Base):
    __tablename__ = "tutors"

    id: Mapped[int] = mapped_column(primary_key=True)
    # shown as first typed; matched on name_key, so "Demo Tutor" and "demo  tutor" are one tutor
    name: Mapped[str] = mapped_column(String(200))
    name_key: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processing', 'done', 'failed')", name="status_valid"),
        Index("ix_evaluations_tutor_id_class_date", "tutor_id", "class_date"),
        # one evaluation per link and rubric, like cache_key for uploads; uploads leave source_url empty
        UniqueConstraint("source_url", "rubric_version", "llm_model", name="uq_evaluations_source_url"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    # a link is only hashed once the worker has downloaded it, so these three start empty for links;
    # a link that turns out to be an already evaluated video keeps cache_key empty and copies the result
    cache_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    video_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    video_path: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    tutor_id: Mapped[int] = mapped_column(ForeignKey("tutors.id"))
    batch_id: Mapped[str] = mapped_column(String(20))
    class_date: Mapped[date] = mapped_column(Date)
    level: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    stage: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(String(40))
    rule_applied: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict | None] = mapped_column(JSONColumn)
    facts: Mapped[dict | None] = mapped_column(JSONColumn)
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    llm_cost_usd: Mapped[float | None]
    retry_count: Mapped[int | None]
    runs_used: Mapped[int | None]
    # QA review: the label and verdicts QA settled on; the system's own stay in label and result
    qa_label: Mapped[str | None] = mapped_column(String(40))
    qa_overrides: Mapped[dict | None] = mapped_column(JSONColumn)
    # the "Needs QA check" criteria QA ticked as checked; only these count toward criterion agreement
    qa_checked: Mapped[list | None] = mapped_column(JSONColumn)
    qa_comment: Mapped[str | None] = mapped_column(Text)
    reviewer: Mapped[str | None] = mapped_column(String(200))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rubric_version: Mapped[str] = mapped_column(String(40))
    llm_model: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tutor: Mapped[Tutor] = relationship()
