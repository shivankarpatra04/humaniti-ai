import logging
from collections.abc import Callable
from pathlib import Path

import anthropic
from sqlalchemy.orm import Session
from yt_dlp.utils import DownloadError

from app.config import settings
from app.core.hashing import cache_key
from app.db import crud
from app.db.database import SessionLocal
from app.db.models import Evaluation
from app.llm.client import evaluate_with_vote
from app.llm.prompt import user_message
from app.pipeline import ingest
from app.pipeline.facts import prepare_class

logger = logging.getLogger(__name__)


def evaluate_job(evaluation_id: int) -> None:
    """RQ entry point; every failure ends as a failed evaluation with a message the user can act on."""
    with SessionLocal() as session:
        evaluation = session.get_one(Evaluation, evaluation_id)

        def set_stage(stage: str) -> None:
            logger.info("evaluation %d: %s", evaluation_id, stage)
            crud.set_stage(session, evaluation_id, stage)

        try:
            _evaluate(session, evaluation, set_stage)
        except Exception as error:
            stage = evaluation.stage
            logger.exception("evaluation %d failed while %s", evaluation_id, stage)
            session.rollback()
            crud.save_error(session, evaluation_id, f"Failed while {stage}: {failure_message(error)}")


def failure_message(error: Exception) -> str:
    if isinstance(error, DownloadError):
        return f"could not download the link ({str(error).removeprefix('ERROR: ')})"
    if isinstance(error, anthropic.APIError):
        return f"Anthropic API error ({error.message})"
    return str(error) or type(error).__name__


def _evaluate(session: Session, evaluation: Evaluation, set_stage: Callable[[str], None]) -> None:
    if evaluation.video_path is None and _download(session, evaluation, set_stage):
        return
    work = settings.work_dir / evaluation.video_sha256
    tutor = evaluation.tutor.name
    segments, facts = prepare_class(Path(evaluation.video_path), work, tutor, set_stage)

    set_stage("llm")
    history = crud.tutor_history(session, evaluation.tutor_id, before=evaluation.class_date)
    message = user_message(
        evaluation.batch_id, evaluation.class_date, tutor, evaluation.level, facts, history, segments
    )
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    result, usage = evaluate_with_vote(client, message, facts, history)

    set_stage("saving")
    prompt_keys = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    crud.save_result(
        session,
        evaluation.id,
        result=result.model_dump(),
        facts=facts,
        input_tokens=sum(usage[key] for key in prompt_keys),
        output_tokens=usage["output_tokens"],
        llm_cost_usd=usage["cost_usd"],
        retry_count=usage["retries"],
        runs_used=usage["runs"],
    )
    ingest.remove_media(work)
    logger.info("evaluation %d: done", evaluation.id)


def _download(session: Session, evaluation: Evaluation, set_stage: Callable[[str], None]) -> bool:
    """Download a link; True when the video turns out to be evaluated already and its result was copied."""
    set_stage("downloading")
    video, sha256 = ingest.download_link(evaluation.source_url)
    key = cache_key(sha256, evaluation.rubric_version, evaluation.llm_model)
    copied = crud.attach_video(session, evaluation, video.as_posix(), sha256, key)
    if copied:
        logger.info("evaluation %d: same video as an earlier evaluation, result copied", evaluation.id)
    return copied
