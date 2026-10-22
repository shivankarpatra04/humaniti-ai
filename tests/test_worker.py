import subprocess
from datetime import date
from pathlib import Path

import anthropic
import httpx2
import pytest
from conftest import LINK, LINK_FORM, SHA256, finished_evaluation, upload
from yt_dlp.utils import DownloadError

from app.config import settings
from app.core.hashing import cache_key
from app.db import crud
from app.llm.prompt import RUBRIC_VERSION
from app.queue import tasks


def test_link_to_an_already_evaluated_video_copies_the_result(api, sessions, monkeypatch):
    stored = finished_evaluation(sessions, cache_key=cache_key(SHA256, RUBRIC_VERSION, settings.llm_model),
                                 video_sha256=SHA256, video_path=f"data/uploads/{SHA256}.mp4")  # fmt: skip
    downloaded = Path(f"data/uploads/{SHA256}.mp4"), SHA256
    monkeypatch.setattr(tasks.ingest, "download_link", lambda url: downloaded)

    linked = api.post("/evaluations", data=LINK_FORM).json()
    tasks.evaluate_job(linked["id"])

    body = api.get(f"/evaluations/{linked['id']}").json()
    assert (body["status"], body["label"]) == ("done", "Good")
    assert (body["llm_cost_usd"], body["retry_count"], body["runs_used"]) == (0, 0, 0)
    assert linked["id"] != stored
    with sessions() as session:
        history = crud.tutor_history(session, crud.find_tutor(session, "Demo Tutor").id, before=date.max)
    assert len(history["classes"]) == 1


def test_bad_link_fails_with_the_reason_and_can_be_resubmitted(api, queue, monkeypatch):
    def bad_link(url):
        raise DownloadError(f"ERROR: [generic] Unsupported URL: {url}")

    monkeypatch.setattr(tasks.ingest, "download_link", bad_link)
    submitted = api.post("/evaluations", data=LINK_FORM).json()

    tasks.evaluate_job(submitted["id"])

    failed = api.get(f"/evaluations/{submitted['id']}").json()
    assert (failed["status"], failed["stage"]) == ("failed", "failed")
    assert failed["error"] == (
        f"Failed while downloading: could not download the link ([generic] Unsupported URL: {LINK})"
    )

    again = api.post("/evaluations", data=LINK_FORM).json()
    assert (again["id"], again["status"], again["stage"]) == (submitted["id"], "pending", "queued")
    assert again["error"] is None
    assert queue.count == 2


def clip(path: Path, with_audio: bool) -> bytes:
    """A 3-minute clip, small and quick to make at 1 frame per second."""
    inputs = ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=1:duration=180"]
    if with_audio:
        inputs += ["-f", "lavfi", "-i", "sine=frequency=440:duration=180"]
    subprocess.run(["ffmpeg", "-v", "error", *inputs, str(path)], check=True)
    return path.read_bytes()


@pytest.mark.parametrize(
    "with_audio, max_video_s, reason",
    [
        (False, 3 * 3600, "the video has no audio stream, so the class cannot be evaluated"),
        (True, 120, "the video is 3 min long; the limit is 2 min"),
    ],
    ids=["no audio stream", "too long"],
)
def test_unusable_video_fails_clearly(api, monkeypatch, tmp_path, with_audio, max_video_s, reason):
    monkeypatch.setattr(settings, "max_video_s", max_video_s)
    submitted = upload(api, clip(tmp_path / "class.mp4", with_audio))

    tasks.evaluate_job(submitted["id"])

    body = api.get(f"/evaluations/{submitted['id']}").json()
    assert (body["status"], body["error"]) == ("failed", f"Failed while extracting: {reason}")


def test_anthropic_error_fails_with_a_clear_reason(api, monkeypatch):
    submitted = upload(api)
    facts = {"bg_8x8_present": True, "class_start": "02:00"}
    monkeypatch.setattr(tasks, "prepare_class", lambda video, work, tutor, set_stage: ([], facts))

    def overloaded(*args):
        request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx2.Response(529, request=request)
        raise anthropic.InternalServerError("Overloaded", response=response, body=None)

    monkeypatch.setattr(tasks, "evaluate_with_vote", overloaded)

    tasks.evaluate_job(submitted["id"])

    body = api.get(f"/evaluations/{submitted['id']}").json()
    assert (body["status"], body["error"]) == ("failed", "Failed while llm: Anthropic API error (Overloaded)")
