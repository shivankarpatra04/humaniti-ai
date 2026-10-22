import re
from typing import Literal

from pydantic import BaseModel, model_validator

Label = Literal["Excellent", "Good", "Average", "Weak", "Known quality issues"]
CriterionName = Literal[
    "bg_8x8",
    "camera_on",
    "lighting",
    "rapport",
    "new_joiner_intro",
    "individual_attention",
    "homework",
    "conclusion",
    "energy",
    "clarity",
    "extras",
]
# only not_met counts; partly is a suggestion and never moves the label
PROCESS_GAPS = ("rapport", "new_joiner_intro", "camera_on", "conclusion")
SOFT_GAPS = ("homework", "energy", "lighting", "clarity")
# rule ids in rubric.md start with the label's letter: K1, W1, A1, G1, E1
RULE_PREFIX = {"Known quality issues": "K", "Weak": "W", "Average": "A", "Good": "G", "Excellent": "E"}
# judged from the transcript alone, so a not_met has to point at the moment and quote it
EVIDENCED = ("rapport", "new_joiner_intro", "conclusion")
TIMESTAMP = re.compile(r"\d{1,3}:\d{2}")
QUOTE = re.compile(r'["“][^"”]{3,}["”]')


# not_applicable only for new_joiner_intro when nobody new joins; it counts as met
Verdict = Literal["met", "partly", "not_met", "not_applicable"]
# agreed with QA on 10 videos (decision 32); the others are shown to QA as "Needs QA check"
MEASURED = ("bg_8x8", "camera_on", "lighting", "homework", "individual_attention")
NEEDS_QA_CHECK = ("rapport", "new_joiner_intro", "energy", "conclusion", "clarity", "extras")


class Criterion(BaseModel):
    criterion: CriterionName
    verdict: Verdict
    timestamp: str
    evidence: str
    suggestion: str


class ClassEvaluation(BaseModel):
    label: Label
    rule_applied: str
    summary: str
    criteria: list[Criterion]
    strengths: list[str]
    issues: list[str]

    @model_validator(mode="after")
    def every_criterion_once_and_rule_matches_label(self) -> "ClassEvaluation":
        names = [c.criterion for c in self.criteria]
        expected = list(CriterionName.__args__)
        if sorted(names) != sorted(expected):
            missing = sorted(set(expected) - set(names))
            raise ValueError(f"criteria must list each of {expected} exactly once; missing {missing}")
        misplaced = [c.criterion for c in self.criteria if c.verdict == "not_applicable"]
        if set(misplaced) - {"new_joiner_intro"}:
            raise ValueError(f"not_applicable is only allowed for new_joiner_intro, not {misplaced}")
        if not self.rule_applied.startswith(RULE_PREFIX[self.label]):
            raise ValueError(
                f"rule_applied {self.rule_applied!r} does not belong to label {self.label!r}; "
                f"its rule id must start with {RULE_PREFIX[self.label]!r}"
            )
        return self

    def not_met(self, names: tuple[str, ...]) -> list[str]:
        return [c.criterion for c in self.criteria if c.criterion in names and c.verdict == "not_met"]

    def unsupported_not_met(self) -> list[Criterion]:
        """Transcript-based not_met verdicts without an mm:ss timestamp and a quoted line as evidence."""
        return [
            c
            for c in self.criteria
            if c.criterion in EVIDENCED
            and c.verdict == "not_met"
            and not (TIMESTAMP.fullmatch(c.timestamp) and QUOTE.search(c.evidence))
        ]


def decide_label(evaluation: ClassEvaluation, facts: dict, history: dict) -> tuple[str, str]:
    """The label the rubric rules give for these verdicts and facts, as (label, rule)."""
    process = evaluation.not_met(PROCESS_GAPS)
    gaps = len(process) + len(evaluation.not_met(SOFT_GAPS))
    # tutor_history already keeps only criteria not_met in at least history_repeat_min earlier classes
    repeated = history["repeated_issues"]
    if not facts["bg_8x8_present"]:
        return "Known quality issues", "K1 no 8x8 background"
    if facts["tutor_absent"] and process:
        return "Known quality issues", "K2 tutor not visible and a process gap"
    if any(name in repeated for name in evaluation.not_met(CriterionName.__args__)):
        return "Known quality issues", "K3 repeated issue"
    if len(process) >= 2:
        return "Weak", "W1 two or more process gaps"
    if gaps >= 2:
        return "Average", "A1 two or more gaps"
    if gaps == 1:
        return "Good", "G1 one gap"
    return "Excellent", "E1 no gaps"


def label_confidence(evaluation: ClassEvaluation, facts: dict, history: dict) -> tuple[str, list[str]]:
    """High when no "Needs QA check" verdict could change the label on its own, else low with those criteria.

    K1 rests on the background alone; K2 with two process gaps survives either one being wrong.
    """
    label = decide_label(evaluation, facts, history)[0]
    deciding = []
    for index, criterion in enumerate(evaluation.criteria):
        if criterion.criterion not in NEEDS_QA_CHECK:
            continue
        flipped = evaluation.model_copy(deep=True)
        flipped.criteria[index].verdict = "met" if criterion.verdict == "not_met" else "not_met"
        if decide_label(flipped, facts, history)[0] != label:
            deciding.append(criterion.criterion)
    return ("low" if deciding else "high"), deciding
