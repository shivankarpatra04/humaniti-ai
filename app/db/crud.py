from collections import Counter
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Evaluation, Tutor


def tutor_key(name: str) -> str:
    return " ".join(name.split()).casefold()


def find_by_key(session: Session, cache_key: str) -> Evaluation | None:
    return session.scalar(select(Evaluation).where(Evaluation.cache_key == cache_key))


def find_by_url(session: Session, url: str, rubric_version: str, llm_model: str) -> Evaluation | None:
    """The latest evaluation of this link under the current rubric and model."""
    return session.scalar(
        select(Evaluation)
        .where(
            Evaluation.source_url == url,
            Evaluation.rubric_version == rubric_version,
            Evaluation.llm_model == llm_model,
        )
        .order_by(Evaluation.id.desc())
    )


def find_tutor(session: Session, name: str) -> Tutor | None:
    return session.scalar(select(Tutor).where(Tutor.name_key == tutor_key(name)))


def get_or_create_tutor(session: Session, name: str) -> Tutor:
    tutor = find_tutor(session, name)
    if tutor:
        return tutor
    tutor = Tutor(name=" ".join(name.split()), name_key=tutor_key(name))
    session.add(tutor)
    session.flush()
    return tutor


def create(
    session: Session,
    *,
    tutor_name: str,
    batch_id: str,
    class_date: date,
    level: str,
    rubric_version: str,
    llm_model: str,
    cache_key: str | None = None,
    video_sha256: str | None = None,
    video_path: str | None = None,
    source_url: str | None = None,
) -> Evaluation:
    evaluation = Evaluation(
        cache_key=cache_key,
        video_sha256=video_sha256,
        video_path=video_path,
        source_url=source_url,
        tutor=get_or_create_tutor(session, tutor_name),
        batch_id=batch_id.upper(),
        class_date=class_date,
        level=level,
        status="pending",
        stage="queued",
        rubric_version=rubric_version,
        llm_model=llm_model,
    )
    session.add(evaluation)
    session.commit()
    return evaluation


def requeue(session: Session, evaluation: Evaluation) -> None:
    """A failed evaluation runs again; the worker reuses the audio, frames and transcript already on disk."""
    evaluation.status, evaluation.stage = "pending", "queued"
    evaluation.error = evaluation.finished_at = None
    session.commit()


def attach_video(session: Session, evaluation: Evaluation, video_path: str, sha256: str, key: str) -> bool:
    """Record the downloaded video of a link; True when that video was already evaluated and is copied."""
    evaluation.video_path, evaluation.video_sha256 = video_path, sha256
    twin = find_by_key(session, key)
    if twin and twin.status == "done":
        for column in ("label", "rule_applied", "summary", "result", "facts"):
            setattr(evaluation, column, getattr(twin, column))
        # no new LLM call was made for this copy
        evaluation.input_tokens = evaluation.output_tokens = evaluation.retry_count = evaluation.runs_used = 0
        evaluation.llm_cost_usd = 0.0
        evaluation.status, evaluation.stage, evaluation.finished_at = "done", "done", datetime.now(UTC)
        session.commit()
        return True
    if twin and twin.status != "failed":
        raise RuntimeError(f"The same video is already being evaluated (evaluation {twin.id})")
    if twin:
        # the failed upload gives its key to this link, which reuses its cached steps
        twin.cache_key = None
        session.flush()
    evaluation.cache_key = key
    session.commit()
    return False


def set_stage(session: Session, evaluation_id: int, stage: str) -> None:
    evaluation = session.get_one(Evaluation, evaluation_id)
    evaluation.status = "processing"
    evaluation.stage = stage
    session.commit()


def save_result(
    session: Session,
    evaluation_id: int,
    *,
    result: dict,
    facts: dict,
    input_tokens: int,
    output_tokens: int,
    llm_cost_usd: float,
    retry_count: int,
    runs_used: int,
) -> None:
    evaluation = session.get_one(Evaluation, evaluation_id)
    evaluation.status = "done"
    evaluation.stage = "done"
    evaluation.error = None
    evaluation.label = result["label"]
    evaluation.rule_applied = result["rule_applied"]
    evaluation.summary = result["summary"]
    evaluation.result = result
    evaluation.facts = facts
    evaluation.input_tokens = input_tokens
    evaluation.output_tokens = output_tokens
    evaluation.llm_cost_usd = llm_cost_usd
    evaluation.retry_count = retry_count
    evaluation.runs_used = runs_used
    evaluation.finished_at = datetime.now(UTC)
    session.commit()


def save_error(session: Session, evaluation_id: int, error: str) -> None:
    evaluation = session.get_one(Evaluation, evaluation_id)
    evaluation.status = "failed"
    evaluation.stage = "failed"
    evaluation.error = error
    evaluation.finished_at = datetime.now(UTC)
    session.commit()


def qa_verdicts(evaluation: Evaluation) -> dict[str, str]:
    """The system's verdicts with QA's overrides on top."""
    verdicts = {c["criterion"]: c["verdict"] for c in evaluation.result["criteria"]}
    return verdicts | (evaluation.qa_overrides or {})


def tutor_history(session: Session, tutor_id: int, before: date) -> dict:
    """Finished evaluations of this tutor for classes before `before`, oldest first; QA's review wins."""
    evaluations = session.scalars(
        select(Evaluation)
        .where(Evaluation.tutor_id == tutor_id, Evaluation.status == "done", Evaluation.class_date < before)
        # per video the reviewed evaluation comes first, else the newest (a re-run under a newer rubric)
        .order_by(Evaluation.class_date, Evaluation.reviewed_at.is_(None), Evaluation.id.desc())
    ).all()

    classes = []
    not_met_counts = Counter()
    seen_videos = set()
    for evaluation in evaluations:
        # the same video sent again (e.g. as a link) is still one class
        if evaluation.video_sha256 in seen_videos:
            continue
        seen_videos.add(evaluation.video_sha256)
        not_met = [name for name, verdict in qa_verdicts(evaluation).items() if verdict == "not_met"]
        not_met_counts.update(not_met)
        classes.append(
            {
                "class_date": evaluation.class_date.isoformat(),
                "batch_id": evaluation.batch_id,
                "label": evaluation.qa_label or evaluation.label,
                "reviewed": evaluation.reviewed_at is not None,
                "not_met": not_met,
            }
        )

    repeated_issues = {
        criterion: count
        for criterion, count in not_met_counts.items()
        if count >= settings.history_repeat_min
    }
    return {"classes": classes, "repeated_issues": repeated_issues}
