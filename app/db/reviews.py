from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import to_ist
from app.db.models import Evaluation
from app.llm.schemas import NEEDS_QA_CHECK


def save_review(
    session: Session,
    evaluation: Evaluation,
    *,
    qa_label: str,
    qa_overrides: dict,
    qa_checked: list[str],
    qa_comment: str,
    reviewer: str,
) -> None:
    """Only overrides that differ from the system's verdict are kept, so they measure disagreement.

    Choosing a verdict for a "Needs QA check" criterion is checking it, ticked or not."""
    system = {c["criterion"]: c["verdict"] for c in evaluation.result["criteria"]}
    evaluation.qa_label = qa_label
    evaluation.qa_overrides = {name: v for name, v in qa_overrides.items() if system.get(name) != v}
    evaluation.qa_checked = [name for name in NEEDS_QA_CHECK if name in qa_checked or name in qa_overrides]
    evaluation.qa_comment = qa_comment.strip() or None
    evaluation.reviewer = " ".join(reviewer.split())
    evaluation.reviewed_at = datetime.now(UTC)
    session.commit()


def awaiting_review(session: Session) -> set[str]:
    """Hashes of videos whose evaluation is still running or waiting for QA; their files must stay."""
    return set(
        session.scalars(
            select(Evaluation.video_sha256).where(
                Evaluation.status != "failed",
                Evaluation.reviewed_at.is_(None),
                Evaluation.video_sha256.is_not(None),
            )
        )
    )


def agreement(session: Session) -> dict:
    """Label agreement, and criterion agreement over the criteria QA explicitly checked, by IST review week.

    A criterion QA did not check says nothing about agreement, so it is left out rather than counted as
    agreed; measured criteria have no tick and are left out entirely."""
    reviewed = session.scalars(
        select(Evaluation).where(Evaluation.reviewed_at.is_not(None)).order_by(Evaluation.reviewed_at)
    ).all()
    criteria = {name: {"checked": 0, "agreed": 0} for name in NEEDS_QA_CHECK}
    weeks = defaultdict(lambda: {"reviewed": 0, "label_agreed": 0, "checked": 0, "agreed": 0})
    rows = []
    for evaluation in reviewed:
        overrides = evaluation.qa_overrides or {}
        checked = evaluation.qa_checked or []
        agreed = [name for name in checked if name not in overrides]
        for name in checked:
            criteria[name]["checked"] += 1
            criteria[name]["agreed"] += name in agreed
        reviewed_at = to_ist(evaluation.reviewed_at)
        week = weeks[reviewed_at.strftime("%G-W%V")]
        week["reviewed"] += 1
        week["label_agreed"] += evaluation.qa_label == evaluation.label
        week["checked"] += len(checked)
        week["agreed"] += len(agreed)
        rows.append(
            {
                "id": evaluation.id,
                "class_date": evaluation.class_date.isoformat(),
                "batch_id": evaluation.batch_id,
                "tutor": evaluation.tutor.name,
                "label": evaluation.label,
                "qa_label": evaluation.qa_label,
                "checked": checked,
                "overridden": sorted(overrides),
                "reviewer": evaluation.reviewer,
                "reviewed_at": reviewed_at.isoformat(),
            }
        )
    totals = {key: sum(week[key] for week in weeks.values()) for key in ("label_agreed", "checked", "agreed")}
    return {
        "reviewed": len(reviewed),
        **totals,
        "criteria": criteria,
        "weeks": [{"week": week, **counts} for week, counts in weeks.items()],
        "rows": rows,
    }
