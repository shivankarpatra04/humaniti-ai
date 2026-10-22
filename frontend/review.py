"""QA's review of a finished evaluation: the label, the criteria QA checked, overrides and a comment."""

from datetime import datetime, timedelta, timezone

import streamlit as st
from api import call_api, detail
from criteria import MEASURED, NEEDS_QA_CHECK, VERDICTS, criterion_name

LABELS = ["Excellent", "Good", "Average", "Weak", "Known quality issues"]
KEEP = "– keep –"
# same as app/config.py: Asia/Kolkata has no daylight saving, so a fixed offset is exact
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def ist(timestamp: str) -> str:
    return datetime.fromisoformat(timestamp).astimezone(IST).strftime("%d/%m/%Y %H:%M IST")


def summary(evaluation: dict) -> None:
    if not evaluation["reviewed_at"]:
        return
    verdict = "accepted" if evaluation["qa_label"] == evaluation["label"] else "changed the label to"
    text = (
        f"**Reviewed** by {evaluation['reviewer']} on {ist(evaluation['reviewed_at'])}: "
        f"{verdict} **{evaluation['qa_label']}**."
    )
    checked = evaluation["qa_checked"] or []
    text += f"  \nChecked: {', '.join(map(criterion_name, checked)) or 'none'}."
    overrides = evaluation["qa_overrides"] or {}
    if overrides:
        changes = ", ".join(f"{criterion_name(c)} → {v.replace('_', ' ')}" for c, v in overrides.items())
        text += f"  \nOverridden: {changes}."
    if evaluation["qa_comment"]:
        text += f"  \nComment: {evaluation['qa_comment']}"
    st.success(text)


def override(evaluation: dict, name: str, system: str, label: str, **kwargs) -> str | None:
    """A verdict selectbox that starts on QA's earlier override, or on keeping the system's verdict."""
    options = [KEEP, "met", "partly", "not_met"]
    if name == "new_joiner_intro":
        options.append("not_applicable")
    previous = (evaluation["qa_overrides"] or {}).get(name, KEEP)
    key = f"verdict_{evaluation['id']}_{name}"
    choice = st.selectbox(label, options, index=options.index(previous), key=key,
                          format_func=lambda option: VERDICTS.get(option, f"{VERDICTS[system]} (system)"),
                          **kwargs)  # fmt: skip
    return None if choice == KEEP else choice


def form(evaluation: dict) -> None:
    st.markdown("#### QA review")
    current = evaluation["qa_label"] or evaluation["label"]
    system = {c["criterion"]: c["verdict"] for c in evaluation["result"]["criteria"]}
    checked_before = evaluation["qa_checked"] or []
    checked, overrides = [], {}
    with st.form(f"review_{evaluation['id']}"):
        qa_label = st.selectbox("Label", LABELS, index=LABELS.index(current))
        st.markdown("**Needs QA check**")
        st.caption("Tick what you checked in the recording; only ticked criteria count toward agreement.")
        for name in NEEDS_QA_CHECK:
            tick, choice = st.columns([3, 2], vertical_alignment="center")
            key = f"checked_{evaluation['id']}_{name}"
            if tick.checkbox(criterion_name(name), value=name in checked_before, key=key):
                checked.append(name)
            with choice:
                hidden = {"label_visibility": "collapsed"}
                overrides[name] = override(evaluation, name, system[name], "Verdict", **hidden)
        with st.expander("Override measured criteria (optional)"):
            for name in MEASURED:
                overrides[name] = override(evaluation, name, system[name], criterion_name(name))
        comment = st.text_area("Comment", value=evaluation["qa_comment"] or "")
        reviewer = st.text_input("Reviewer *", value=evaluation["reviewer"] or "")
        left, right = st.columns(2)
        accept = left.form_submit_button(f"Accept {evaluation['label']}", type="primary", width="stretch")
        save = right.form_submit_button("Save with this label", width="stretch")
    if not (accept or save):
        return
    if not reviewer.strip():
        st.error("Please enter the reviewer's name.")
        return
    review = {
        "qa_label": evaluation["label"] if accept else qa_label,
        "qa_overrides": {name: verdict for name, verdict in overrides.items() if verdict},
        "qa_checked": checked,
        "qa_comment": comment,
        "reviewer": reviewer,
    }
    response = call_api("POST", f"/evaluations/{evaluation['id']}/review", json=review)
    if not response.ok:
        st.error(detail(response))
        return
    st.rerun()
