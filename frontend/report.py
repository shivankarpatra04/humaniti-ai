"""The QA review report of one finished evaluation, on screen and as Markdown."""

import json
from datetime import date

import player
import review
import streamlit as st
from criteria import MEASURED, NEEDS_QA_CHECK, VERDICTS, criterion_name

# approximate, only to show the cost in rupees next to the dollar amount
INR_PER_USD = 88
SECTIONS = {
    "Measured": (MEASURED, "Measured by code, or agreed with QA on all 10 calibration videos."),
    "Needs QA check": (
        NEEDS_QA_CHECK,
        "Judged from the transcript, where QA disagreed most: check the evidence.",
    ),
}
# participants_seen_on_name_cards is left out on purpose: it lists student names
KEY_FACTS = {
    "duration": "Duration",
    "class_start": "Class start",
    "bg_8x8_pct": "8×8 background (% of frames)",
    "bg_8x8_first_seen": "8×8 background first seen",
    "tutor_camera_off_during_class_s": "Tutor camera off in class (s)",
    "tutor_camera_off_during_class": "Tutor camera off at",
    "tutor_camera_off_uncertain": "Camera-off total too close to call",
    "tutor_present_pct": "Tutor in own camera (%)",
    "tutor_face_visible_pct": "Face clearly visible (%)",
    "lighting_ok": "Lighting OK",
    "lighting_uncertain": "Lighting too close to call",
    "tutor_out_of_frame_intervals": "Tutor out of frame",
    "loudness_lufs": "Loudness (LUFS)",
    "words_per_min": "Words per minute",
    "speech_ratio": "Share of time with speech",
    "pitch_variation_semitones": "Pitch variation (semitones)",
    "long_silences": "Silences over 1 min",
}


def header(evaluation: dict) -> str:
    class_date = date.fromisoformat(evaluation["class_date"]).strftime("%d/%m/%Y")
    return f"{evaluation['batch_id']} | {class_date} | {evaluation['tutor']}"


def suggestion(evaluation: dict) -> str:
    line = f"Suggested label: **{evaluation['label']}** ({evaluation['rule_applied']}), "
    if evaluation["confidence"] == "high":
        return line + "confidence **high**: it rests on measured criteria only."
    deciding = ", ".join(criterion_name(c) for c in evaluation["confidence_criteria"])
    return line + f"confidence **low**: it depends on {deciding}."


def findings(evaluation: dict) -> list[str]:
    """Summary, ✅ strengths and ❌ issues as Markdown lines; two trailing spaces keep one per line."""
    result = evaluation["result"]
    lines = [f"*{_plain(result['summary'])}*", ""]
    lines += [f"✅ {_plain(strength)}  " for strength in result["strengths"]]
    return lines + [f"❌ {_plain(issue)}  " for issue in result["issues"]]


def _plain(text: str) -> str:
    """Claude writes QA style like "8*8 background"; the asterisk must not start italics."""
    return text.replace("*", "\\*").replace("_", "\\_")


def criteria_rows(evaluation: dict, names: tuple[str, ...]) -> list[dict]:
    by_name = {c["criterion"]: c for c in evaluation["result"]["criteria"]}
    overrides = evaluation.get("qa_overrides") or {}
    checked = evaluation.get("qa_checked") or []
    return [
        {
            "Criterion": criterion_name(name),
            "Verdict": VERDICTS[by_name[name]["verdict"]],
            "QA": VERDICTS[overrides[name]] if name in overrides else "checked, agrees" * (name in checked),
            "Time": by_name[name]["timestamp"],
            "Evidence": by_name[name]["evidence"],
            "Suggestion": by_name[name]["suggestion"],
        }
        for name in names
    ]


def fact_rows(facts: dict) -> list[dict]:
    return [{"Fact": label, "Value": _value(facts[key])} for key, label in KEY_FACTS.items() if key in facts]


def _value(value) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "none"
    return str(value)


def cost_line(evaluation: dict) -> str:
    cost = evaluation["llm_cost_usd"] or 0
    return (
        f"LLM cost ${cost:.4f} (≈ ₹{cost * INR_PER_USD:.2f}), {evaluation['input_tokens']} input and "
        f"{evaluation['output_tokens']} output tokens, {evaluation['runs_used']} runs, "
        f"{evaluation['retry_count']} retries"
    )


def markdown(evaluation: dict) -> str:
    def table(rows: list[dict]) -> list[str]:
        columns = list(rows[0])
        lines = ["| " + " | ".join(columns) + " |", "|" + "---|" * len(columns)]
        for row in rows:
            lines.append("| " + " | ".join(str(row[c]).replace("|", "\\|") for c in columns) + " |")
        return lines

    lines = [f"# {header(evaluation)}", "", suggestion(evaluation), ""]
    if evaluation.get("reviewed_at"):
        reviewed = f"reviewed by {evaluation['reviewer']} on {review.ist(evaluation['reviewed_at'])}"
        lines += [f"QA label: **{evaluation['qa_label']}** ({reviewed})", ""]
    lines += findings(evaluation)
    for title, (names, _) in SECTIONS.items():
        lines += ["", f"## {title}", "", *table(criteria_rows(evaluation, names))]
    lines += ["", "## Key facts", "", *table(fact_rows(evaluation["facts"])), "", cost_line(evaluation), ""]
    return "\n".join(lines)


def show(evaluation: dict, segments: list[dict] | None) -> None:
    st.subheader(header(evaluation))
    st.markdown(suggestion(evaluation))
    review.summary(evaluation)
    st.markdown("\n".join(findings(evaluation)))

    video_column, review_column = st.columns(2)
    with video_column:
        player.show(evaluation["id"])
    with review_column:
        review.form(evaluation)

    for title, (names, caption) in SECTIONS.items():
        st.markdown(f"#### {title}")
        st.caption(caption)
        for row, name in zip(criteria_rows(evaluation, names), names, strict=True):
            verdict, times, evidence = st.columns([2, 1, 6])
            qa = f"  \nQA: {row['QA']}" if row["QA"] else ""
            verdict.markdown(f"**{row['Criterion']}**  \n{row['Verdict']}{qa}")
            with times:
                player.seek_buttons(evaluation["id"], f"{row['Time']} {row['Evidence']}", key=name)
            note = f"  \n*Suggestion:* {_plain(row['Suggestion'])}" if row["Suggestion"] else ""
            evidence.markdown(_plain(row["Evidence"]) + note)

    st.markdown("#### Key facts")
    st.table(fact_rows(evaluation["facts"]), border="horizontal", hide_index=True)
    st.caption(cost_line(evaluation))
    stem = f"{evaluation['batch_id']}_{evaluation['class_date']}_evaluation"
    left, right = st.columns(2)
    left.download_button("Download JSON", json.dumps(evaluation, indent=2, ensure_ascii=False),
                         file_name=f"{stem}.json", mime="application/json", width="stretch")  # fmt: skip
    right.download_button("Download Markdown", markdown(evaluation), file_name=f"{stem}.md",
                          mime="text/markdown", width="stretch")  # fmt: skip

    with st.expander("Transcript", expanded=False):
        if not segments:
            st.caption("No transcript is available for this evaluation.")
        else:
            st.text("\n".join(f"[{player.mmss(s['start'])}] {s['text']}" for s in segments))
