from datetime import date

from app.db import crud


def make_evaluation(session, key: str, tutor_name: str = "Sample Teacher", class_date=date(2026, 8, 28)):
    return crud.create(
        session,
        cache_key=key,
        video_sha256=key.ljust(64, "0"),
        video_path=f"data/uploads/{key}.mp4",
        tutor_name=tutor_name,
        batch_id="b435",
        class_date=class_date,
        level="Intermediate",
        rubric_version="r1",
        llm_model="claude-haiku-5-5",
    )


def finish(session, evaluation, not_met: list[str]):
    criteria = [{"criterion": c, "verdict": "not_met"} for c in not_met]
    criteria.append({"criterion": "background", "verdict": "met"})
    result = {"label": "Weak", "rule_applied": "no rapport", "summary": "s", "criteria": criteria}
    crud.save_result(
        session,
        evaluation.id,
        result=result,
        facts={},
        input_tokens=10,
        output_tokens=5,
        llm_cost_usd=0.001,
        retry_count=0,
        runs_used=1,
    )


def test_create_and_find_by_key_reuses_normalised_tutor(session):
    first = make_evaluation(session, "a", tutor_name="  TSP   Demo ")
    second = make_evaluation(session, "b", tutor_name="tsp demo")

    assert first.tutor_id == second.tutor_id
    assert first.tutor.name == "TSP Demo"
    assert first.batch_id == "B435"
    assert crud.find_by_key(session, "a").id == first.id
    assert crud.find_by_key(session, "missing") is None


def test_stage_result_and_error_update_status(session):
    evaluation = make_evaluation(session, "a")
    assert (evaluation.status, evaluation.stage) == ("pending", "queued")
    crud.set_stage(session, evaluation.id, "transcribing")
    assert (evaluation.status, evaluation.stage) == ("processing", "transcribing")

    finish(session, evaluation, ["homework"])
    assert evaluation.status == "done"
    assert evaluation.label == "Weak"
    assert evaluation.stage == "done"
    assert evaluation.finished_at is not None

    failed = make_evaluation(session, "b")
    crud.save_error(session, failed.id, "ffmpeg: no audio stream")
    assert (failed.status, failed.stage, failed.error) == ("failed", "failed", "ffmpeg: no audio stream")


def test_tutor_history_counts_repeated_issues_from_earlier_finished_classes(session):
    finish(session, make_evaluation(session, "a", class_date=date(2026, 7, 1)), ["rapport", "homework"])
    finish(session, make_evaluation(session, "b", class_date=date(2026, 7, 8)), ["rapport"])
    finish(session, make_evaluation(session, "c", class_date=date(2026, 7, 15)), [])
    crud.save_error(session, make_evaluation(session, "d", class_date=date(2026, 7, 20)).id, "boom")
    later = make_evaluation(session, "e", class_date=date(2026, 9, 1))
    finish(session, later, ["rapport"])
    other_tutor = make_evaluation(session, "f", tutor_name="Other Person", class_date=date(2026, 7, 2))
    finish(session, other_tutor, ["rapport"])

    history = crud.tutor_history(session, later.tutor_id, before=date(2026, 8, 28))

    assert [c["class_date"] for c in history["classes"]] == ["2026-07-01", "2026-07-08", "2026-07-15"]
    assert history["classes"][0]["not_met"] == ["rapport", "homework"]
    assert history["repeated_issues"] == {"rapport": 2}
