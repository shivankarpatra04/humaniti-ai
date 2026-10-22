import os

# set before any app import so tests never reach Supabase, even with a filled-in .env
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["ANTHROPIC_API_KEY"] = "test"
os.environ["API_KEY"] = "test-api-key"

import hashlib  # noqa: E402
from datetime import date  # noqa: E402

import fakeredis  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from rq import Queue  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api.main import app  # noqa: E402
from app.api.routes import get_queue, get_session  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import crud  # noqa: E402
from app.db.models import Base  # noqa: E402
from app.llm.prompt import RUBRIC_VERSION  # noqa: E402
from app.llm.schemas import ClassEvaluation, CriterionName, decide_label  # noqa: E402
from app.queue import tasks  # noqa: E402

VIDEO = b"not really a video, but hashed like one"
SHA256 = hashlib.sha256(VIDEO).hexdigest()
FILE_NAME = "B435 Intermediate Part  - 2026-07-25(good).mp4"
LINK = "https://drive.example.com/b435-2026-07-25"
LINK_FORM = {"tutor_name": "Demo Tutor", "url": LINK, "batch_id": "B435", "class_date": "2026-07-25",
             "level": "Intermediate"}  # fmt: skip


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def sessions(monkeypatch):
    # one shared in-memory database for the test, the API thread and the worker job
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(tasks, "SessionLocal", sessions)
    return sessions


@pytest.fixture
def queue():
    return Queue("evaluations", connection=fakeredis.FakeStrictRedis())


@pytest.fixture
def api(sessions, queue, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")

    def test_session():
        with sessions() as session:
            yield session

    app.dependency_overrides = {get_session: test_session, get_queue: lambda: queue}
    yield TestClient(app, headers={"X-API-Key": "test-api-key"})
    app.dependency_overrides = {}


FACTS = {"bg_8x8_present": True, "tutor_absent": False}
NO_HISTORY = {"classes": [], "repeated_issues": {}}


def finished_result(not_met: tuple[str, ...], facts: dict) -> dict:
    """A stored result as the worker saves it, labelled by the rules for these verdicts."""
    criteria = [
        {
            "criterion": name,
            "verdict": "not_met" if name in not_met else "met",
            "timestamp": "12:30",
            "evidence": '"Sam, try the next puzzle" at 12:30',
            "suggestion": "",
        }
        for name in CriterionName.__args__
    ]
    body = {"label": "Excellent", "rule_applied": "E1", "summary": "", "strengths": [], "issues": []}
    evaluation = ClassEvaluation.model_validate({**body, "criteria": criteria})
    evaluation.label, evaluation.rule_applied = decide_label(evaluation, facts, NO_HISTORY)
    return evaluation.model_dump()


def finished_evaluation(sessions, not_met: tuple = ("homework",), facts: dict = FACTS, **fields) -> int:
    with sessions() as session:
        defaults = {
            "tutor_name": "Demo Tutor",
            "batch_id": "B435",
            "class_date": date(2026, 7, 25),
            "level": "Intermediate",
            "rubric_version": RUBRIC_VERSION,
            "llm_model": settings.llm_model,
        }
        evaluation = crud.create(session, **{**defaults, **fields})
        result = finished_result(not_met, facts)
        usage = {"input_tokens": 12000, "output_tokens": 2000, "llm_cost_usd": 0.0022, "retry_count": 0,
                 "runs_used": 1}  # fmt: skip
        crud.save_result(session, evaluation.id, result=result, facts=facts, **usage)
        return evaluation.id


def upload(api, content: bytes = VIDEO, file_name: str = FILE_NAME) -> dict:
    form = {"tutor_name": " Demo  Tutor "}
    response = api.post("/evaluations", data=form, files={"file": (file_name, content)})
    assert response.status_code == 200, response.text
    return response.json()
