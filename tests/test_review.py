from datetime import UTC, date, datetime
from urllib.parse import urlsplit

import pytest
from conftest import FACTS, SHA256, VIDEO, finished_evaluation, upload
from fastapi.testclient import TestClient

from app.api.main import app
from app.config import settings
from app.db import reviews
from app.db.models import Evaluation

ACCEPT = {"qa_label": "Good", "qa_checked": ["rapport"], "qa_comment": "agree, should give HWs",
          "reviewer": " Demo  Reviewer "}  # fmt: skip


def test_accept_then_change_the_label_with_overrides(api, sessions):
    evaluation_id = finished_evaluation(sessions)
    suggested = api.get(f"/evaluations/{evaluation_id}").json()
    assert (suggested["label"], suggested["reviewed_at"], suggested["confidence"]) == ("Good", None, "low")

    accepted = api.post(f"/evaluations/{evaluation_id}/review", json=ACCEPT).json()
    assert (accepted["qa_label"], accepted["qa_overrides"]) == ("Good", {})
    assert accepted["qa_checked"] == ["rapport"]
    assert accepted["reviewer"] == "Demo Reviewer"
    assert accepted["reviewed_at"].endswith("+05:30")

    # homework not_met is what the system already said, so only energy is a real override;
    # choosing a verdict for energy is checking it, even without the tick
    overrides = {"energy": "not_met", "homework": "not_met"}
    changed = {**ACCEPT, "qa_label": "Average", "qa_overrides": overrides, "qa_checked": [], "qa_comment": ""}
    body = api.post(f"/evaluations/{evaluation_id}/review", json=changed).json()

    assert (body["label"], body["qa_label"]) == ("Good", "Average")
    assert (body["qa_overrides"], body["qa_comment"]) == ({"energy": "not_met"}, None)
    assert body["qa_checked"] == ["energy"]


@pytest.mark.parametrize(
    "review, status",
    [
        ({**ACCEPT, "reviewer": "  "}, 422),
        ({**ACCEPT, "qa_label": "Brilliant"}, 422),
        ({**ACCEPT, "qa_overrides": {"punctuality": "met"}}, 422),
        ({**ACCEPT, "qa_overrides": {"homework": "not_applicable"}}, 422),
        ({**ACCEPT, "qa_checked": ["homework"]}, 422),
    ],
    ids=[
        "blank reviewer",
        "unknown label",
        "unknown criterion",
        "not_applicable outside new joiners",
        "measured criterion ticked",
    ],  # fmt: skip
)
def test_invalid_reviews_are_rejected(api, sessions, review, status):
    evaluation_id = finished_evaluation(sessions)
    assert api.post(f"/evaluations/{evaluation_id}/review", json=review).status_code == status


def test_only_finished_evaluations_can_be_reviewed(api):
    pending = upload(api)
    assert api.post(f"/evaluations/{pending['id']}/review", json=ACCEPT).status_code == 409


@pytest.mark.parametrize(
    "facts, not_met, confidence, rule",
    [
        ({"bg_8x8_present": False, "tutor_absent": None}, ("rapport",), "high", "K1"),
        ({"bg_8x8_present": True, "tutor_absent": True}, ("rapport", "conclusion"), "high", "K2"),
        ({"bg_8x8_present": True, "tutor_absent": True}, ("rapport",), "low", "K2"),
        (FACTS, ("homework", "lighting"), "high", "A1"),
        (FACTS, ("homework",), "low", "G1"),
    ],
    ids=[
        "no background",
        "absent tutor, two process gaps",
        "absent tutor, one process gap",
        "two measured gaps: a third gap is still Average",
        "one gap: a rapport gap would make it Average",
    ],
)
def test_confidence_is_high_only_when_no_qa_check_decides(api, sessions, facts, not_met, confidence, rule):
    evaluation_id = finished_evaluation(sessions, not_met=not_met, facts=facts)

    body = api.get(f"/evaluations/{evaluation_id}").json()

    assert body["rule_applied"].startswith(rule) and body["confidence"] == confidence
    assert (confidence == "high") == (body["confidence_criteria"] == [])


def test_history_uses_the_qa_label_and_overrides(api, sessions):
    # the system saw no rapport problem in two classes; QA overrode it both times
    for day, sha256 in ((4, "a" * 64), (11, "b" * 64)):
        evaluation_id = finished_evaluation(sessions, class_date=date(2026, 7, day), video_sha256=sha256)
        review = {**ACCEPT, "qa_label": "Weak", "qa_overrides": {"rapport": "not_met"}}
        api.post(f"/evaluations/{evaluation_id}/review", json=review)

    history = api.get("/tutors/demo tutor/history").json()

    assert [c["label"] for c in history["classes"]] == ["Weak", "Weak"]
    assert history["repeated_issues"] == {"homework": 2, "rapport": 2}

    # a video evaluated twice (old and new rubric): the reviewed evaluation counts, not the first one
    same_video = {"class_date": date(2026, 7, 18), "video_sha256": "c" * 64}
    finished_evaluation(sessions, **same_video, cache_key="old rubric")
    rerun = finished_evaluation(sessions, **same_video, cache_key="new rubric")
    api.post(f"/evaluations/{rerun}/review", json={**ACCEPT, "qa_label": "Average"})

    history = api.get("/tutors/demo tutor/history").json()
    assert (history["classes"][-1]["label"], history["classes"][-1]["reviewed"]) == ("Average", True)


def test_agreement_counts_only_checked_criteria(api, sessions):
    accepted, changed, _unreviewed = (finished_evaluation(sessions, video_sha256=c * 64) for c in "abc")
    api.post(f"/evaluations/{accepted}/review", json={**ACCEPT, "qa_checked": ["rapport", "energy"]})
    review = {**ACCEPT, "qa_label": "Average", "qa_overrides": {"energy": "not_met"}}
    api.post(f"/evaluations/{changed}/review", json=review)

    agreement = api.get("/agreement").json()

    assert (agreement["reviewed"], agreement["label_agreed"]) == (2, 1)
    assert agreement["criteria"]["rapport"] == {"checked": 2, "agreed": 2}
    assert agreement["criteria"]["energy"] == {"checked": 2, "agreed": 1}
    # never ticked: no agreement claimed, and measured criteria have no tick at all
    assert agreement["criteria"]["conclusion"] == {"checked": 0, "agreed": 0}
    assert "homework" not in agreement["criteria"]
    assert (agreement["checked"], agreement["agreed"]) == (4, 3)
    assert [(w["reviewed"], w["label_agreed"], w["checked"]) for w in agreement["weeks"]] == [(2, 1, 4)]


def test_review_weeks_and_times_are_in_ist(api, sessions):
    evaluation_id = finished_evaluation(sessions)
    api.post(f"/evaluations/{evaluation_id}/review", json=ACCEPT)
    # Sunday 20:00 UTC is already Monday 01:30 in India, the next ISO week
    with sessions() as session:
        session.get(Evaluation, evaluation_id).reviewed_at = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
        session.commit()

    agreement = api.get("/agreement").json()

    assert agreement["weeks"][0]["week"] == "2026-W44"
    assert agreement["rows"][0]["reviewed_at"] == "2026-10-26T01:30:00+05:30"


def test_the_video_streams_through_a_signed_link(api):
    evaluation_id = upload(api)["id"]
    link = api.get(f"/evaluations/{evaluation_id}/video-url").json()
    url = urlsplit(link["url"])
    assert f"{url.scheme}://{url.netloc}" == settings.public_api_url
    # the browser sends no API key, only the link; Range requests let the player seek
    browser = TestClient(app)
    video = f"{url.path}?{url.query}"
    response = browser.get(video, headers={"Range": "bytes=4-9"})
    assert (response.status_code, response.content) == (206, VIDEO[4:10])
    assert browser.get(video.replace("token=", "token=0")).status_code == 403
    assert browser.get(f"/evaluations/{evaluation_id}/video").status_code == 403

    (settings.uploads_dir / f"{SHA256}.mp4").unlink()
    assert browser.get(video).status_code == 404
    assert api.get(f"/evaluations/{evaluation_id}/video-url").status_code == 404


def test_video_link_keeps_the_proxy_prefix(api, monkeypatch):
    # in production Caddy serves the API under /api, and the player must ask for the video there
    monkeypatch.setattr(settings, "public_api_url", "https://demo.sslip.io/api/")
    evaluation_id = upload(api)["id"]

    link = api.get(f"/evaluations/{evaluation_id}/video-url").json()["url"]

    assert link.startswith(f"https://demo.sslip.io/api/evaluations/{evaluation_id}/video?expires=")


def test_video_links_expire(api, monkeypatch):
    evaluation_id = upload(api)["id"]
    link = urlsplit(api.get(f"/evaluations/{evaluation_id}/video-url").json()["url"])
    monkeypatch.setattr("time.time", lambda: datetime.now(UTC).timestamp() + settings.video_url_ttl_s + 1)

    assert TestClient(app).get(f"{link.path}?{link.query}").status_code == 403


def test_videos_wait_for_review_before_cleanup(api, sessions):
    evaluation_id = finished_evaluation(sessions, video_sha256=SHA256)
    with sessions() as session:
        assert reviews.awaiting_review(session) == {SHA256}

    api.post(f"/evaluations/{evaluation_id}/review", json=ACCEPT)

    with sessions() as session:
        assert reviews.awaiting_review(session) == set()
