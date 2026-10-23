import json
import secrets
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from redis.exceptions import RedisError
from rq import Queue
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.schemas import EvaluationOut, TutorHistory
from app.config import settings
from app.core.hashing import cache_key
from app.db import crud
from app.db.database import SessionLocal
from app.db.models import Evaluation
from app.llm.prompt import RUBRIC_VERSION
from app.llm.schemas import ClassEvaluation, label_confidence
from app.pipeline.ingest import parse_file_name, save_upload
from app.queue import connection


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = settings.api_key.get_secret_value()
    if x_api_key is None or not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(401, "Missing or wrong X-API-Key header.")


router = APIRouter(dependencies=[Depends(require_api_key)])
# /health stays open so Docker and uptime checks need no key
public = APIRouter()


def get_session():
    with SessionLocal() as session:
        yield session


def get_queue() -> Queue:
    return connection.queue


SessionDep = Annotated[Session, Depends(get_session)]
QueueDep = Annotated[Queue, Depends(get_queue)]


@router.post("/evaluations", response_model=EvaluationOut)
def submit_evaluation(
    session: SessionDep,
    queue: QueueDep,
    tutor_name: Annotated[str, Form(min_length=1)],
    file: Annotated[UploadFile | None, File()] = None,
    url: Annotated[str | None, Form()] = None,
    batch_id: Annotated[str | None, Form()] = None,
    class_date: Annotated[date | None, Form()] = None,
    level: Annotated[str | None, Form()] = None,
):
    """A stored result comes back at once; anything else is queued and polled with GET /evaluations/{id}."""
    if (file is None) == (url is None):
        raise HTTPException(422, "Send either a video file or a url.")
    if url and not url.strip().startswith(("http://", "https://")):
        raise HTTPException(422, "The url must start with http:// or https://.")
    parsed = parse_file_name(file.filename or "") if file else {}
    metadata = {
        "batch_id": batch_id or parsed.get("batch_id"),
        "class_date": class_date or parsed.get("class_date"),
        "level": level or parsed.get("level"),
    }
    missing = [name for name, value in metadata.items() if not value]
    if missing:
        raise HTTPException(422, f"Missing {', '.join(missing)}; it could not be read from the file name.")
    common = {"tutor_name": tutor_name, "rubric_version": RUBRIC_VERSION, "llm_model": settings.llm_model}

    if url:
        url = url.strip()
        existing = crud.find_by_url(session, url, RUBRIC_VERSION, settings.llm_model)
        if existing:
            return _resume(session, queue, existing)
        try:
            created = crud.create(session, **common, **metadata, source_url=url)
        except IntegrityError:
            # the same link was submitted twice at once and the other request inserted it first
            session.rollback()
            return _resume(session, queue, crud.find_by_url(session, url, RUBRIC_VERSION, settings.llm_model))
        return _enqueue(session, queue, created)

    if file.size and file.size > settings.max_upload_mb << 20:
        raise HTTPException(413, f"The file is larger than {settings.max_upload_mb} MB.")
    try:
        video, sha256 = save_upload(file.file, file.filename or "")
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    key = cache_key(sha256, RUBRIC_VERSION, settings.llm_model)
    existing = crud.find_by_key(session, key)
    if existing:
        return _resume(session, queue, existing)
    try:
        created = crud.create(
            session, **common, **metadata, cache_key=key, video_sha256=sha256, video_path=video.as_posix()
        )
    except IntegrityError:
        session.rollback()
        return _resume(session, queue, crud.find_by_key(session, key))
    return _enqueue(session, queue, created)


def _resume(session: Session, queue: Queue, evaluation: Evaluation) -> Evaluation:
    """A finished or running evaluation is returned as it is; a failed one runs again."""
    if evaluation.status != "failed":
        return evaluation
    crud.requeue(session, evaluation)
    return _enqueue(session, queue, evaluation)


def _enqueue(session: Session, queue: Queue, evaluation: Evaluation) -> Evaluation:
    try:
        queue.enqueue("app.queue.tasks.evaluate_job", evaluation.id, job_timeout=settings.job_timeout_s)
    except RedisError as error:
        crud.save_error(session, evaluation.id, "The job queue (Redis) is unavailable; send the class again.")
        raise HTTPException(503, "The job queue (Redis) is unavailable.") from error
    return evaluation


def find_evaluation(session: Session, evaluation_id: int) -> Evaluation:
    evaluation = session.get(Evaluation, evaluation_id)
    if evaluation is None:
        raise HTTPException(404, f"Evaluation {evaluation_id} not found.")
    return evaluation


def evaluation_out(session: Session, evaluation: Evaluation) -> EvaluationOut:
    out = EvaluationOut.model_validate(evaluation)
    if evaluation.status == "done":
        history = crud.tutor_history(session, evaluation.tutor_id, before=evaluation.class_date)
        result = ClassEvaluation.model_validate(evaluation.result)
        out.confidence, out.confidence_criteria = label_confidence(result, evaluation.facts, history)
    return out


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationOut)
def get_evaluation(evaluation_id: int, session: SessionDep):
    return evaluation_out(session, find_evaluation(session, evaluation_id))


@router.get("/evaluations/{evaluation_id}/transcript")
def get_transcript(evaluation_id: int, session: SessionDep) -> list[dict]:
    """Segments [{start, end, text}]; kept on disk only, so the report loads it on demand."""
    sha256 = find_evaluation(session, evaluation_id).video_sha256
    transcript = settings.work_dir / f"{sha256}" / "transcript.json"
    if sha256 is None or not transcript.exists():
        raise HTTPException(404, f"No transcript for evaluation {evaluation_id} yet.")
    return json.loads(transcript.read_text(encoding="utf-8"))


@router.get("/tutors/{name}/history", response_model=TutorHistory)
def get_tutor_history(name: str, session: SessionDep):
    tutor = crud.find_tutor(session, name)
    if tutor is None:
        raise HTTPException(404, f"No evaluations for tutor {name.strip()!r}.")
    return {"tutor": tutor.name, **crud.tutor_history(session, tutor.id, before=date.max)}


@public.get("/health")
def health(session: SessionDep, queue: QueueDep) -> dict:
    session.execute(text("SELECT 1"))
    queue.connection.ping()
    return {"status": "ok", "queued_jobs": queue.count}
