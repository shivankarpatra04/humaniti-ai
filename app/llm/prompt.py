import hashlib
import json
from datetime import date
from pathlib import Path

from app.config import settings
from app.pipeline.video_facts import mmss

RUBRIC = (Path(__file__).parent / "prompts" / "rubric.md").read_text(encoding="utf-8")
# part of the cache key, so editing the rubric re-evaluates every video
RUBRIC_VERSION = hashlib.sha256(RUBRIC.encode()).hexdigest()[:8]
# the rubric is identical for every video, so it is cached and only the class itself is paid in full
SYSTEM = [{"type": "text", "text": RUBRIC, "cache_control": {"type": "ephemeral"}}]


def user_message(
    batch_id: str, class_date: date, tutor: str, level: str, facts: dict, history: dict, segments: list[dict]
) -> str:
    minutes, seconds = facts["class_start"].split(":")
    class_start = int(minutes) * 60 + int(seconds)
    # a missing greeting or recap cannot be quoted, so the lines where it should have been are the evidence
    opening = [s for s in segments if s["end"] > class_start][: settings.opening_lines]
    closing = segments[-settings.opening_lines :]
    return (
        f"Class: batch {batch_id} | date {class_date.isoformat()} | tutor {tutor} | level {level}\n\n"
        f"Facts (measured by code, ground truth):\n{json.dumps(facts, indent=1, sort_keys=True)}\n\n"
        f"Tutor history:\n{json.dumps(history, indent=1, sort_keys=True)}\n\n"
        f"Class opening (the first {len(opening)} lines from class_start {facts['class_start']}):\n"
        f"{_lines(opening)}\n\n"
        f"Class closing (the last {len(closing)} lines):\n{_lines(closing)}\n\n"
        f"Transcript:\n{_lines(segments)}"
    )


def _lines(segments: list[dict]) -> str:
    return "\n".join(f"[{mmss(s['start'])}] {s['text']}" for s in segments)
