from fastapi import APIRouter, Depends, HTTPException

from app.api.routes import SessionDep, evaluation_out, find_evaluation, require_api_key
from app.api.schemas import EvaluationOut, ReviewIn
from app.db import reviews
from app.llm.schemas import NEEDS_QA_CHECK

router = APIRouter(dependencies=[Depends(require_api_key)])


@router.post("/evaluations/{evaluation_id}/review", response_model=EvaluationOut)
def review_evaluation(evaluation_id: int, review: ReviewIn, session: SessionDep):
    """QA's decision; sending it again replaces the earlier review."""
    evaluation = find_evaluation(session, evaluation_id)
    if evaluation.status != "done":
        raise HTTPException(409, "Only a finished evaluation can be reviewed.")
    misplaced = [name for name, verdict in review.qa_overrides.items() if verdict == "not_applicable"]
    if set(misplaced) - {"new_joiner_intro"}:
        raise HTTPException(422, f"not_applicable is only allowed for new_joiner_intro, not {misplaced}.")
    unticked = set(review.qa_checked) - set(NEEDS_QA_CHECK)
    if unticked:
        raise HTTPException(422, f"Only 'Needs QA check' criteria can be ticked, not {sorted(unticked)}.")
    reviews.save_review(session, evaluation, **review.model_dump())
    return evaluation_out(session, evaluation)


@router.get("/agreement")
def get_agreement(session: SessionDep) -> dict:
    return reviews.agreement(session)
