"""Adaptive majority vote over Claude runs, and the uncertainty bands of measured facts."""

from collections import Counter

from app.llm.schemas import ClassEvaluation, CriterionName, decide_label

# camera_on and lighting follow measured facts; these are the verdicts that vary between runs
JUDGED_GAPS = ("rapport", "new_joiner_intro", "conclusion", "homework", "energy", "clarity")


def apply_bands(evaluation: ClassEvaluation, facts: dict) -> None:
    """A measurement too close to its threshold to call is partly at most, whatever the run said."""
    uncertain = set()
    if facts.get("tutor_camera_off_uncertain"):
        uncertain.add("camera_on")
    # being out of frame is a camera-position fault of its own, whatever the brightness
    if facts.get("lighting_uncertain") and not facts.get("tutor_out_of_frame_intervals"):
        uncertain.add("lighting")
    for criterion in evaluation.criteria:
        if criterion.criterion in uncertain and criterion.verdict == "not_met":
            criterion.verdict = "partly"


def on_boundary(evaluation: ClassEvaluation, facts: dict, history: dict) -> bool:
    """True when one judged verdict crossing the gap line would change the label.

    Between runs Haiku moves verdicts one step (met-partly, partly-not_met); a met never became not_met in the
    calibration runs, so only partly and not_met verdicts are treated as able to cross.
    """
    label = decide_label(evaluation, facts, history)[0]
    for index, criterion in enumerate(evaluation.criteria):
        if criterion.criterion not in JUDGED_GAPS or criterion.verdict not in ("partly", "not_met"):
            continue
        flipped = evaluation.model_copy(deep=True)
        flipped.criteria[index].verdict = "partly" if criterion.verdict == "not_met" else "not_met"
        if decide_label(flipped, facts, history)[0] != label:
            return True
    return False


def majority(runs: list[ClassEvaluation], facts: dict, history: dict) -> ClassEvaluation:
    """Each verdict by majority (three different verdicts give partly), the label recomputed by code.

    The text comes from the run that agrees most with the majority; criteria where it disagrees are taken
    from a run that has the majority verdict, so evidence always matches the verdict.
    """
    verdicts = {}
    for name in CriterionName.__args__:
        votes = Counter(c.verdict for run in runs for c in run.criteria if c.criterion == name)
        verdict, count = votes.most_common(1)[0]
        verdicts[name] = verdict if count > 1 or len(runs) == 1 else "partly"

    def agreement(run: ClassEvaluation) -> int:
        return sum(c.verdict == verdicts[c.criterion] for c in run.criteria)

    final = max(runs, key=agreement).model_copy(deep=True)
    for index, criterion in enumerate(final.criteria):
        wanted = verdicts[criterion.criterion]
        if criterion.verdict == wanted:
            continue
        donors = [c for run in runs for c in run.criteria if c.criterion == criterion.criterion]
        final.criteria[index] = next((c for c in donors if c.verdict == wanted), criterion.model_copy())
        final.criteria[index].verdict = wanted
    final.label, rule = decide_label(final, facts, history)
    final.rule_applied = rule if len(runs) == 1 else f"{rule} (vote of {len(runs)} runs)"
    return final
