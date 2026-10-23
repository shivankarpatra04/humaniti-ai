import pytest
from conftest import FILE_NAME, LINK, LINK_FORM, SHA256, VIDEO, finished_evaluation, upload

from app.config import settings
from app.core.hashing import cache_key
from app.db import crud
from app.llm.prompt import RUBRIC_VERSION
from app.queue import tasks


def test_upload_cache_miss_saves_the_video_and_enqueues(api, queue):
    body = upload(api)

    assert (body["status"], body["stage"], body["tutor"]) == ("pending", "queued", "Demo Tutor")
    assert (body["batch_id"], body["class_date"], body["level"]) == ("B435", "2026-07-25", "Intermediate")
    assert (settings.uploads_dir / f"{SHA256}.mp4").read_bytes() == VIDEO
    [job] = queue.jobs
    assert (job.func_name, job.args) == ("app.queue.tasks.evaluate_job", (body["id"],))


def test_upload_cache_hit_returns_the_stored_result_without_queueing(api, sessions, queue):
    stored = finished_evaluation(sessions, cache_key=cache_key(SHA256, RUBRIC_VERSION, settings.llm_model),
                                 video_sha256=SHA256, video_path=f"data/uploads/{SHA256}.mp4")  # fmt: skip

    body = upload(api)

    assert (body["id"], body["status"], body["label"]) == (stored, "done", "Good")
    assert body["llm_cost_usd"] == 0.0022
    assert queue.count == 0


def test_upload_over_the_limit_is_refused_before_saving(api, queue, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)

    response = api.post("/evaluations", data={"tutor_name": "Demo Tutor"}, files={"file": (FILE_NAME, VIDEO)})

    assert response.status_code == 413
    assert not settings.uploads_dir.exists() and queue.count == 0


@pytest.mark.parametrize("key", [None, "wrong-key"], ids=["missing key", "wrong key"])
def test_routes_need_the_api_key_except_health(api, sessions, key):
    stored = finished_evaluation(sessions, source_url=LINK)
    headers = {"X-API-Key": key} if key else {}
    api.headers.pop("X-API-Key")

    assert api.get(f"/evaluations/{stored}", headers=headers).status_code == 401
    assert api.get("/tutors/Demo Tutor/history", headers=headers).status_code == 401
    assert api.post("/evaluations", data=LINK_FORM, headers=headers).status_code == 401
    assert api.get("/health").json()["status"] == "ok"


@pytest.mark.parametrize("submit", ["upload", "link"])
def test_concurrent_duplicate_returns_the_first_insert(api, sessions, queue, monkeypatch, submit):
    stored = finished_evaluation(sessions, cache_key=cache_key(SHA256, RUBRIC_VERSION, settings.llm_model),
                                 video_sha256=SHA256, source_url=LINK)  # fmt: skip
    # the lookup runs before the other request has committed, so it finds nothing and the insert collides
    lookup = "find_by_url" if submit == "link" else "find_by_key"
    real_lookup, calls = getattr(crud, lookup), []

    def lookup_before_the_other_commit(*args):
        calls.append(args)
        return None if len(calls) == 1 else real_lookup(*args)

    monkeypatch.setattr(crud, lookup, lookup_before_the_other_commit)

    body = upload(api) if submit == "upload" else api.post("/evaluations", data=LINK_FORM).json()

    assert (body["id"], body["status"]) == (stored, "done")
    assert queue.count == 0


def test_same_link_returns_the_stored_result_without_downloading(api, sessions, queue, monkeypatch):
    stored = finished_evaluation(sessions, source_url=LINK)
    monkeypatch.setattr(tasks.ingest, "download_link", lambda url: pytest.fail("downloaded again"))

    body = api.post("/evaluations", data=LINK_FORM).json()

    assert (body["id"], body["status"], body["label"]) == (stored, "done", "Good")
    assert queue.count == 0


def test_transcript_comes_from_the_work_folder(api):
    submitted = upload(api)
    assert api.get(f"/evaluations/{submitted['id']}/transcript").status_code == 404

    work = settings.work_dir / SHA256
    work.mkdir(parents=True)
    (work / "transcript.json").write_text('[{"start": 1.0, "end": 2.5, "text": "hello chess friends"}]')

    assert api.get(f"/evaluations/{submitted['id']}/transcript").json()[0]["text"] == "hello chess friends"


def test_missing_metadata_and_unknown_ids_are_reported(api):
    response = api.post("/evaluations", data={"tutor_name": "Demo"}, files={"file": ("zoom.mp4", VIDEO)})
    assert response.status_code == 422 and "batch_id, class_date, level" in response.json()["detail"]
    assert api.get("/evaluations/999").status_code == 404
    assert api.get("/tutors/nobody/history").status_code == 404
