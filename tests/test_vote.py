from datetime import date

from test_llm_schema import FACTS, NO_HISTORY, fake_client, reply

from app.llm.client import evaluate_with_vote
from app.llm.prompt import user_message

GOOD = {"label": "Good", "rule": "G1 one gap", "not_met": ("rapport",)}


def test_clear_label_needs_one_run():
    # all met: no judged verdict sits next to the gap line
    client = fake_client(reply())

    evaluation, usage = evaluate_with_vote(client, "Class: B472 ...", FACTS, NO_HISTORY)

    assert (evaluation.label, evaluation.rule_applied, usage["runs"]) == ("Excellent", "E1 no gaps", 1)


def average(*gaps: str) -> dict:
    return {"label": "Average", "rule": "A1 two or more gaps", "not_met": gaps}


def test_boundary_label_takes_each_verdict_by_majority():
    # rapport not_met could be partly, which would make the class Excellent
    client = fake_client(
        reply(**GOOD, verdicts={"energy": "met"}),
        reply(**average("rapport", "homework"), verdicts={"energy": "partly"}),
        reply(**average("rapport", "energy")),
    )

    evaluation, usage = evaluate_with_vote(client, "Class: B435 ...", FACTS, NO_HISTORY)

    verdicts = {c.criterion: c.verdict for c in evaluation.criteria}
    assert (verdicts["rapport"], verdicts["homework"], verdicts["energy"]) == ("not_met", "met", "partly")
    assert evaluation.label == "Good" and evaluation.rule_applied == "G1 one gap (vote of 3 runs)"
    assert (usage["runs"], usage["input_tokens"]) == (3, 27000)


def test_two_runs_with_the_same_gaps_settle_the_vote():
    client = fake_client(reply(**GOOD), reply(**GOOD, verdicts={"energy": "partly"}))

    evaluation, usage = evaluate_with_vote(client, "Class: B435 ...", FACTS, NO_HISTORY)

    assert (evaluation.label, usage["runs"]) == ("Good", 2)


def test_measurements_too_close_to_call_are_partly_at_most():
    # B516: face brightness 68 against 70; Claude's not_met on lighting must not count as a gap
    facts = {**FACTS, "lighting_uncertain": True, "tutor_out_of_frame_intervals": []}
    client = fake_client(reply(label="Good", rule="G1 one gap", not_met=("lighting",)))

    evaluation, usage = evaluate_with_vote(client, "Class: B516 ...", facts, NO_HISTORY)

    lighting = next(c for c in evaluation.criteria if c.criterion == "lighting")
    assert (lighting.verdict, evaluation.label, usage["runs"]) == ("partly", "Excellent", 1)


def test_prompt_shows_the_class_opening_and_closing():
    starts = (30, 405, 411, 420, 430, 440, 450, 3540)
    segments = [{"start": s, "end": s + 2, "text": f"line at {s}"} for s in starts]

    message = user_message("B482", date(2026, 9, 2), "Demo Tutor", "Intermediate", {"class_start": "06:50"},
                           NO_HISTORY, segments)  # fmt: skip

    opening = message.split("Class opening")[1].split("Class closing")[0]
    assert "[06:51] line at 411" in opening and "line at 30" not in opening and "line at 405" not in opening
    assert "[59:00] line at 3540" in message.split("Class closing")[1].split("Transcript:")[0]
