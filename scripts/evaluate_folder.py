"""Calibration: evaluate every video in a folder and compare with the QA label in its file name.

Each video's tutor comes from <folder>/tutors.json ({"<file name>": "<tutor name>"}); name-card matching needs
it. Nothing is written to the database and tutor history stays empty, so each pass judges every class on its
own. Transcripts and facts cached in data/work/ are reused; only the LLM runs again.

    python -m scripts.evaluate_folder samples
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import anthropic

from app.config import settings
from app.core.hashing import sha256_file
from app.llm.client import evaluate_with_vote
from app.llm.prompt import RUBRIC_VERSION, user_message
from app.pipeline.facts import prepare_class
from app.pipeline.ingest import VIDEO_SUFFIXES, parse_file_name

logger = logging.getLogger("evaluate_folder")

LABELS = {
    "Excellent": "Exc",
    "Good": "Good",
    "Average": "Avg",
    "Weak": "Weak",
    "Known quality issues": "Known",
}
# QA writes the label in brackets after the date, spelled loosely: "( excelent )", "(weeK )"
NAME_LABELS = {
    "excel": "Excellent",
    "good": "Good",
    "average": "Average",
    "weak": "Weak",
    "week": "Weak",
    "quality": "Known quality issues",
}
NO_HISTORY = {"classes": [], "repeated_issues": {}}


def expected_label(file_name: str) -> str | None:
    tail = file_name.lower().rsplit("-", 1)[-1]
    return next((label for word, label in NAME_LABELS.items() if word in tail), None)


def evaluate(video: Path, tutor: str, client: anthropic.Anthropic) -> dict:
    started = time.monotonic()
    parsed = parse_file_name(video.name)
    work = settings.work_dir / sha256_file(video)
    segments, facts = prepare_class(
        video, work, tutor, lambda stage: logger.info("%s: %s", video.name, stage)
    )
    message = user_message(
        parsed["batch_id"], parsed["class_date"], tutor, parsed["level"], facts, NO_HISTORY, segments
    )
    result, usage = evaluate_with_vote(client, message, facts, NO_HISTORY)
    return {
        "video": f"{parsed['batch_id']} {parsed['class_date']:%d/%m}",
        "expected": expected_label(video.name),
        "label": result.label,
        "rule": result.rule_applied,
        "runs": usage["runs"],
        "retries": usage["retries"],
        "cost_usd": usage["cost_usd"],
        "seconds": round(time.monotonic() - started),
        "verdicts": {c.criterion: c.verdict for c in result.criteria},
    }


def print_report(rows: list[dict], seconds: float) -> None:
    print(f"\nrubric {RUBRIC_VERSION}, model {settings.llm_model}\n")
    print(f"{'video':<12}{'expected':<9}{'label':<9}{'runs':>5}{'cost $':>9}{'time':>7}  rule")
    for row in rows:
        expected = LABELS.get(row["expected"], "?")
        print(f"{row['video']:<12}{expected:<9}{LABELS[row['label']]:<9}{row['runs']:>5}"
              f"{row['cost_usd']:>9.4f}{row['seconds']:>6}s  {row['rule']}")  # fmt: skip

    print("\nconfusion matrix (rows: QA label, columns: Humaniti AI)")
    print(" " * 7 + "".join(f"{short:>7}" for short in LABELS.values()))
    for expected, short in LABELS.items():
        counts = [sum(r["expected"] == expected and r["label"] == label for r in rows) for label in LABELS]
        print(f"{short:<7}" + "".join(f"{count:>7}" for count in counts))

    labelled = [r for r in rows if r["expected"]]
    matches = sum(r["label"] == r["expected"] for r in labelled)
    total = sum(r["cost_usd"] for r in rows)
    average = total / len(rows)
    print(f"\nmatches {matches}/{len(labelled)}; runs {sum(r['runs'] for r in rows)} for {len(rows)} videos")
    inr = settings.inr_per_usd
    print(f"cost ${total:.4f} (₹{total * inr:.2f}) total, ${average:.4f} (₹{average * inr:.2f}) per video")
    print(f"runtime {seconds // 60:.0f} min {seconds % 60:.0f} s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    folder = parser.parse_args().folder
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s: %(message)s")
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    sys.stdout.reconfigure(encoding="utf-8")

    tutors = json.loads((folder / "tutors.json").read_text(encoding="utf-8"))
    videos = sorted(path for path in folder.iterdir() if path.suffix.lower() in VIDEO_SUFFIXES)
    missing = [video.name for video in videos if video.name not in tutors]
    if missing:
        sys.exit(f"add the tutor of these videos to {folder / 'tutors.json'}: {missing}")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key.get_secret_value())
    started = time.monotonic()
    rows = [evaluate(video, tutors[video.name], client) for video in videos]
    print_report(rows, time.monotonic() - started)

    # verdicts only, no transcript text, so passes can be compared later
    out = settings.data_dir / "calibration" / f"{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rubric_version": RUBRIC_VERSION, "rows": rows}, indent=1))
    print(f"saved {out}")


if __name__ == "__main__":
    main()
