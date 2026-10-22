from datetime import date

import report
from conftest import finished_evaluation
from criteria import CRITERIA
from history import history_rows


def criterion(name: str, verdict: str = "met", timestamp: str = "", evidence: str = "", suggestion: str = ""):
    return {"criterion": name, "verdict": verdict, "timestamp": timestamp, "evidence": evidence,
            "suggestion": suggestion}  # fmt: skip


EVALUATION = {
    "id": 4,
    "batch_id": "B435",
    "class_date": "2026-07-25",
    "tutor": "Demo Tutor",
    "label": "Good",
    "rule_applied": "G1 one gap",
    "confidence": "low",
    "confidence_criteria": ["rapport"],
    "qa_label": "Average",
    "qa_overrides": {"rapport": "not_met"},
    "qa_checked": ["rapport", "energy"],
    "reviewer": "Demo Reviewer",
    "reviewed_at": "2026-10-23T09:30:00+00:00",
    "result": {
        "summary": "fixed 8*8 background, consider everyone in class, should give HWs",
        "strengths": ["greeted every student by name from 02:53"],
        "issues": ["no homework given before the goodbye at 31:37"],
        "criteria": [criterion(name) for name in CRITERIA if name not in ("rapport", "homework")]
        + [
            criterion("rapport", timestamp="02:53", evidence="a | b"),
            criterion("homework", "not_met", "31:37", "goodbye", "give a puzzle sheet as HW"),
        ],
    },
    "facts": {
        "bg_8x8_present": True,
        "lighting_ok": True,
        "long_silences": ["28:19-29:23"],
        "participants_seen_on_name_cards": ["A student"],
    },
    "llm_cost_usd": 0.0026,
    "input_tokens": 10401,
    "output_tokens": 2847,
    "retry_count": 0,
    "runs_used": 3,
}


def test_markdown_report_in_review_sections():
    markdown = report.markdown(EVALUATION)

    assert markdown.startswith("# B435 | 25/07/2026 | Demo Tutor\n")
    assert "Suggested label: **Good** (G1 one gap), confidence **low**" in markdown
    assert "it depends on Rapport before teaching." in markdown
    assert "QA label: **Average** (reviewed by Demo Reviewer on 23/10/2026 15:00 IST)" in markdown
    assert r"*fixed 8\*8 background, consider everyone in class, should give HWs*" in markdown
    assert "✅ greeted every student by name from 02:53" in markdown
    measured, needs_check = markdown.split("## Measured")[1].split("## Needs QA check")
    assert "| Homework | ❌ not met |  | 31:37 | goodbye | give a puzzle sheet as HW |" in measured
    assert r"| Rapport before teaching | ✅ met | ❌ not met | 02:53 | a \| b |  |" in needs_check
    assert "| Energy and pleasant interaction | ✅ met | checked, agrees |" in needs_check
    assert "| Lighting OK | yes |" in markdown and "| Silences over 1 min | 28:19-29:23 |" in markdown
    assert "A student" not in markdown
    assert "LLM cost $0.0026" in markdown and "3 runs" in markdown


def test_history_marks_criteria_repeated_as_not_met(api, sessions):
    # two earlier classes, both without homework
    for day, sha256 in ((18, "a" * 64), (25, "b" * 64)):
        finished_evaluation(sessions, class_date=date(2026, 7, day), video_sha256=sha256)

    history = api.get("/tutors/demo tutor/history").json()
    rows = history_rows(history)

    assert history["repeated_issues"] == {"homework": 2}
    assert [row["Date"] for row in rows] == ["25/07/2026", "18/07/2026"]
    assert rows[0]["Issues (not met)"] == "🔁 Homework"
