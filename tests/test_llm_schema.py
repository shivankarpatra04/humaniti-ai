import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.llm.client import evaluate_class
from app.llm.schemas import ClassEvaluation, CriterionName, decide_label

FACTS = {"bg_8x8_present": True, "tutor_absent": False}
NO_HISTORY = {"classes": [], "repeated_issues": {}}


def body(label="Excellent", rule="E1 no gaps", not_met=(), partly=(), drop=(), quoted=True, verdicts=None):
    def verdict(name):
        if verdicts and name in verdicts:
            return verdicts[name]
        return "not_met" if name in not_met else "partly" if name in partly else "met"

    def evidence(name):
        return (
            '"in the last class we learned" right after hello'
            if quoted and verdict(name) == "not_met"
            else "..."
        )

    return {
        "label": label,
        "rule_applied": rule,
        "summary": "good rapport building, consider everyone in the class, given HWs",
        "criteria": [
            {
                "criterion": c,
                "verdict": verdict(c),
                "timestamp": "02:20",
                "evidence": evidence(c),
                "suggestion": "",
            }
            for c in CriterionName.__args__
            if c not in drop
        ],
        "strengths": ["puzzles given by name from 10:15"],
        "issues": [],
    }


def reply(stop="end_turn", **fields):
    usage = SimpleNamespace(
        input_tokens=9000, output_tokens=1500, cache_read_input_tokens=2500, cache_creation_input_tokens=0
    )
    content = [
        SimpleNamespace(type="thinking", thinking=""),
        SimpleNamespace(type="text", text=json.dumps(body(**fields))),
    ]
    return SimpleNamespace(content=content, usage=usage, stop_reason=stop, stop_details=None)


class FakeMessages:
    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return self.replies.pop(0)


def fake_client(*replies):
    return SimpleNamespace(messages=FakeMessages(replies))


def test_valid_reply_is_parsed_and_costed():
    client = fake_client(reply())

    evaluation, usage = evaluate_class(client, "Class: batch B472 ...", FACTS, NO_HISTORY)

    assert evaluation.label == "Excellent" and len(evaluation.criteria) == 11
    assert usage["cost_usd"] == pytest.approx(9000 * 0.1e-6 + 2500 * 0.01e-6 + 1500 * 0.5e-6)
    request = client.messages.requests[0]
    assert request["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert request["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in request
    assert request["output_config"]["format"]["type"] == "json_schema"


def test_invalid_reply_is_retried_once_with_the_error():
    client = fake_client(reply(drop=("homework",)), reply())

    evaluation, usage = evaluate_class(client, "Class: batch B472 ...", FACTS, NO_HISTORY)

    assert evaluation.label == "Excellent"
    assert usage["input_tokens"] == 18000 and usage["retries"] == 1
    class_block, rejected = client.messages.requests[1]["messages"][0]["content"]
    assert class_block["text"] == "Class: batch B472 ..." and "homework" in rejected["text"]


def test_gives_up_after_the_second_invalid_reply():
    client = fake_client(reply(drop=("homework",)), reply(drop=("homework",)))

    with pytest.raises(ValueError, match="still invalid"):
        evaluate_class(client, "Class: ...", FACTS, NO_HISTORY)
    assert len(client.messages.requests) == 2


def test_label_that_breaks_the_rules_is_retried_then_set_by_code():
    one_process_gap = {"label": "Weak", "rule": "W1 two or more process gaps", "not_met": ("rapport",)}
    client = fake_client(reply(**one_process_gap), reply(**one_process_gap))

    evaluation, _ = evaluate_class(client, "Class: batch B435 ...", FACTS, NO_HISTORY)

    assert "give 'Good'" in client.messages.requests[1]["messages"][0]["content"][1]["text"]
    assert evaluation.label == "Good"
    assert evaluation.rule_applied == "G1 one gap (set by code)"


@pytest.mark.parametrize(
    "facts, history, not_met, partly, expected",
    [
        ({"bg_8x8_present": False, "tutor_absent": None}, NO_HISTORY, (), (), "K1"),
        ({"bg_8x8_present": True, "tutor_absent": True}, NO_HISTORY, ("conclusion",), (), "K2"),
        ({"bg_8x8_present": True, "tutor_absent": True}, NO_HISTORY, ("homework",), (), "G1"),
        (FACTS, {"classes": [], "repeated_issues": {"homework": 2}}, ("homework",), (), "K3"),
        (FACTS, NO_HISTORY, ("rapport", "camera_on"), (), "W1"),
        (FACTS, NO_HISTORY, ("rapport", "homework", "lighting"), (), "A1"),
        (FACTS, NO_HISTORY, ("rapport",), (), "G1"),
        (FACTS, NO_HISTORY, ("individual_attention", "extras"), ("energy", "clarity", "conclusion"), "E1"),
    ],
    ids=[
        "no background",
        "absent tutor with process gap",
        "absent tutor without process gap",
        "repeated issue",
        "two process gaps",
        "one process two soft",
        "one process gap is not weak",
        "partly and non-gap criteria never count",
    ],
)
def test_decide_label(facts, history, not_met, partly, expected):
    evaluation = ClassEvaluation.model_validate(body(not_met=not_met, partly=partly))

    assert decide_label(evaluation, facts, history)[1].startswith(expected)


def test_not_met_without_a_quote_is_retried_then_becomes_partly():
    unsupported = {"label": "Good", "rule": "G1 one gap", "not_met": ("rapport",), "quoted": False}
    client = fake_client(reply(**unsupported), reply(**unsupported))

    evaluation, _ = evaluate_class(client, "Class: batch B435 ...", FACTS, NO_HISTORY)

    assert "double quotes" in client.messages.requests[1]["messages"][0]["content"][1]["text"]
    rapport = next(c for c in evaluation.criteria if c.criterion == "rapport")
    assert rapport.verdict == "partly"
    assert evaluation.label == "Excellent" and evaluation.rule_applied == "E1 no gaps (set by code)"


def test_not_applicable_only_for_new_joiners_and_counts_as_met():
    no_new_joiner = ClassEvaluation.model_validate(body(verdicts={"new_joiner_intro": "not_applicable"}))
    assert decide_label(no_new_joiner, FACTS, NO_HISTORY)[0] == "Excellent"

    with pytest.raises(ValidationError, match="only allowed for new_joiner_intro"):
        ClassEvaluation.model_validate(body(verdicts={"homework": "not_applicable"}))


def test_refusal_fails_the_evaluation():
    with pytest.raises(RuntimeError, match="declined"):
        evaluate_class(fake_client(reply(stop="refusal")), "Class: ...", FACTS, NO_HISTORY)
