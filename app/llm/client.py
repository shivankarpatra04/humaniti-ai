import logging

import anthropic
from pydantic import ValidationError

from app.config import settings
from app.llm.prompt import SYSTEM
from app.llm.schemas import PROCESS_GAPS, SOFT_GAPS, ClassEvaluation, CriterionName, decide_label
from app.llm.vote import apply_bands, majority, on_boundary

logger = logging.getLogger(__name__)

# structured outputs make the reply match the schema; the pydantic checks on top catch what a schema cannot
OUTPUT_FORMAT = {
    "type": "json_schema",
    "schema": anthropic.transform_schema(ClassEvaluation.model_json_schema()),
}
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def evaluate_with_vote(
    client: anthropic.Anthropic, user_message: str, facts: dict, history: dict
) -> tuple[ClassEvaluation, dict]:
    """One run; more only when the label sits on a boundary, then each verdict by majority."""
    run, usage = evaluate_class(client, user_message, facts, history)
    apply_bands(run, facts)
    runs = [run]
    if on_boundary(run, facts, history):
        logger.info("label %s is on a boundary; up to %d more runs", run.label, settings.vote_runs - 1)
        for _ in range(settings.vote_runs - 1):
            run, more = evaluate_class(client, user_message, facts, history)
            apply_bands(run, facts)
            runs.append(run)
            usage = {key: usage[key] + more[key] for key in usage}
            if _gaps(runs[0]) == _gaps(runs[1]):
                # a third run cannot outvote two runs that agree on every gap, so the label is settled
                break
    usage["runs"] = len(runs)
    return majority(runs, facts, history), usage


def _gaps(run: ClassEvaluation) -> set[str]:
    return set(run.not_met(CriterionName.__args__))


def evaluate_class(
    client: anthropic.Anthropic, user_message: str, facts: dict, history: dict
) -> tuple[ClassEvaluation, dict]:
    """One call per class; a reply that is invalid or breaks the rubric is retried once with the reason."""
    usage = dict.fromkeys(USAGE_KEYS, 0)
    # cached, so the extra runs of a vote and a retry read the class at a tenth of the price
    content = [{"type": "text", "text": user_message, "cache_control": {"type": "ephemeral"}}]
    for attempt in (1, 2):
        # no temperature: Haiku 5.5 rejects non-default sampling values
        response = client.messages.create(
            model=settings.llm_model,
            max_tokens=settings.llm_max_tokens,
            system=SYSTEM,
            output_config={"effort": settings.llm_effort, "format": OUTPUT_FORMAT},
            messages=[{"role": "user", "content": content}],
        )
        for key in USAGE_KEYS:
            usage[key] += getattr(response.usage, key) or 0
        if response.stop_reason == "refusal":
            raise RuntimeError(f"Claude declined to evaluate the class: {response.stop_details}")

        text = next((block.text for block in response.content if block.type == "text"), "")
        evaluation, problem = _check(text, facts, history)
        if problem is None:
            break
        if attempt == 1:
            logger.warning("LLM reply rejected (%s), retrying", "rules" if evaluation else "invalid")
            rejected = f"Your previous answer was rejected:\n{problem}\nReturn fixed JSON."
            content = [content[0], {"type": "text", "text": rejected}]
            continue
        if evaluation is None:
            # the reason is left out: it can quote the reply, and with it the transcript
            raise ValueError("Claude's reply was still invalid after a retry")
        _settle(evaluation, facts, history)

    usage["cost_usd"] = cost_usd(usage)
    usage["retries"] = attempt - 1
    logger.info("LLM: %s by rule %s, usage %s", evaluation.label, evaluation.rule_applied[:2], usage)
    return evaluation, usage


def _check(text: str, facts: dict, history: dict) -> tuple[ClassEvaluation | None, str | None]:
    """The parsed reply and what is wrong with it, or None when it is fine."""
    try:
        evaluation = ClassEvaluation.model_validate_json(text)
    except ValidationError as error:
        return None, str(error)
    problems = []
    unsupported = [c.criterion for c in evaluation.unsupported_not_met()]
    if unsupported:
        problems.append(
            f"not_met for {unsupported} needs an mm:ss timestamp and a short transcript quote in double "
            "quotes as evidence; give both, or use partly when the transcript does not clearly show it."
        )
    label, rule = decide_label(evaluation, facts, history)
    if evaluation.label != label:
        process, soft = evaluation.not_met(PROCESS_GAPS), evaluation.not_met(SOFT_GAPS)
        problems.append(
            f"label {evaluation.label!r} does not follow the rules for your own verdicts: process gaps "
            f"{process} and soft gaps {soft} give {label!r} ({rule}). Check the verdicts again, then set "
            "the label the rules give."
        )
    return evaluation, "\n".join(problems) or None


def _settle(evaluation: ClassEvaluation, facts: dict, history: dict) -> None:
    """After the retry: a not_met still without evidence becomes partly, and the label follows the rules."""
    for criterion in evaluation.unsupported_not_met():
        logger.warning("LLM gave %s not_met without evidence twice; using partly", criterion.criterion)
        criterion.verdict = "partly"
    label, rule = decide_label(evaluation, facts, history)
    if evaluation.label != label:
        logger.warning("LLM label %s breaks the rules after a retry; using %s", evaluation.label, label)
        evaluation.label, evaluation.rule_applied = label, f"{rule} (set by code)"


def cost_usd(usage: dict) -> float:
    """Prices for prompts up to 100k tokens; a class transcript stays far below that."""
    per_input = settings.llm_input_usd_per_mtok / 1e6
    return (
        usage["input_tokens"] * per_input
        + usage["cache_creation_input_tokens"] * per_input * settings.llm_cache_write_factor
        + usage["cache_read_input_tokens"] * per_input * settings.llm_cache_read_factor
        + usage["output_tokens"] * settings.llm_output_usd_per_mtok / 1e6
    )
