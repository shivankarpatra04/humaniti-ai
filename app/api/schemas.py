from datetime import date, datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints, field_serializer, field_validator

from app.config import to_ist
from app.llm.schemas import CriterionName, Label, Verdict


class EvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    stage: str | None
    error: str | None
    tutor: str
    batch_id: str
    class_date: date
    level: str
    source_url: str | None
    label: str | None
    rule_applied: str | None
    summary: str | None
    result: dict | None
    facts: dict | None
    input_tokens: int | None
    output_tokens: int | None
    llm_cost_usd: float | None
    retry_count: int | None
    runs_used: int | None
    qa_label: str | None
    qa_overrides: dict | None
    qa_checked: list[str] | None
    qa_comment: str | None
    reviewer: str | None
    reviewed_at: datetime | None
    # how far the suggested label rests on criteria QA should check; computed when read
    confidence: str | None = None
    confidence_criteria: list[str] = []
    created_at: datetime
    finished_at: datetime | None

    @field_validator("tutor", mode="before")
    @classmethod
    def tutor_name(cls, tutor) -> str:
        return tutor.name

    @field_serializer("reviewed_at", "created_at", "finished_at")
    def in_ist(self, moment: datetime | None) -> datetime | None:
        return moment and to_ist(moment)


class ReviewIn(BaseModel):
    """Accepting is sending the suggested label back; overrides list only the criteria QA changes."""

    qa_label: Label
    qa_overrides: dict[CriterionName, Verdict] = {}
    # the "Needs QA check" criteria QA looked at in the recording
    qa_checked: list[CriterionName] = []
    qa_comment: str = ""
    reviewer: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class TutorHistory(BaseModel):
    tutor: str
    classes: list[dict]
    repeated_issues: dict[str, int]
