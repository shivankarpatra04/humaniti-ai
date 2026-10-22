from datetime import date
from urllib.parse import quote

import streamlit as st
from api import call_api, detail
from criteria import criterion_name


def tutor_history() -> None:
    st.title("Tutor history")
    name = st.text_input("Tutor name", placeholder="Demo Tutor")
    if not name.strip():
        return
    response = call_api("GET", f"/tutors/{quote(name.strip())}/history")
    if not response.ok:
        st.info(detail(response))
        return
    history = response.json()
    repeated = history["repeated_issues"]
    count = len(history["classes"])
    st.subheader(f"{history['tutor']}: {count} evaluated class{'' if count == 1 else 'es'}")
    if repeated:
        issues = ", ".join(f"**{criterion_name(c)}** ({n} classes)" for c, n in repeated.items())
        st.warning(f"Repeated as not met: {issues}. Missing it again makes the class Known quality issues.")
    st.dataframe(history_rows(history), hide_index=True, width="stretch")
    if repeated:
        st.caption("🔁 marks a criterion that was not met in two or more classes.")


def history_rows(history: dict) -> list[dict]:
    """Newest class first; criteria repeated as not met get the 🔁 marker."""
    return [
        {
            "Date": date.fromisoformat(c["class_date"]).strftime("%d/%m/%Y"),
            "Batch": c["batch_id"],
            # a QA-reviewed label replaces the suggested one in history and in the repeat count
            "Label": f"{c['label']} (QA)" if c["reviewed"] else f"{c['label']} (suggested)",
            "Issues (not met)": ", ".join(
                ("🔁 " if issue in history["repeated_issues"] else "") + criterion_name(issue)
                for issue in c["not_met"]
            )
            or "none",
        }
        for c in reversed(history["classes"])
    ]
