"""How often QA agrees with the system: the label, and the criteria QA explicitly checked, over time."""

from datetime import date

import streamlit as st
from api import call_api, detail
from criteria import criterion_name
from review import ist


def agreement_page() -> None:
    st.title("Agreement")
    response = call_api("GET", "/agreement")
    if not response.ok:
        st.error(detail(response))
        return
    agreement = response.json()
    if not agreement["reviewed"]:
        st.info(
            "No evaluation has been reviewed yet. Reviews are saved from the QA review form in each report."
        )
        return

    reviews, label, criteria, checked = st.columns(4)
    reviews.metric("Reviewed evaluations", agreement["reviewed"])
    label.metric("Label agreement", percent(agreement["label_agreed"], agreement["reviewed"]),
                 help="QA kept the suggested label")  # fmt: skip
    criteria.metric("Criterion agreement", percent(agreement["agreed"], agreement["checked"]),
                    help="Ticked as checked and not overridden")  # fmt: skip
    checked.metric("Criteria checked", agreement["checked"], help="Ticked by QA, over all reviews")

    st.markdown("#### Per criterion")
    st.caption(
        "Only criteria QA ticked as checked count; one agrees when it was checked and not overridden. "
        "Measured criteria have no tick and are not counted."
    )
    # a neutral hue: red would read as a fault even at 100 %
    bar = st.column_config.ProgressColumn(format="%d %%", min_value=0, max_value=100, color="blue")
    rows = criterion_rows(agreement["criteria"])
    st.dataframe(rows, hide_index=True, width="stretch", height="content", column_config={"Agreement": bar})

    weeks = agreement["weeks"]
    st.markdown("#### By review week (IST)")
    st.dataframe(week_rows(weeks), hide_index=True, width="stretch")
    if len(weeks) >= 2:
        trend = {
            "Week": [w["week"] for w in weeks],
            "Label agreement (%)": [share(w["label_agreed"], w["reviewed"]) for w in weeks],
            "Criterion agreement (%)": [share(w["agreed"], w["checked"]) for w in weeks],
        }
        st.line_chart(trend, x="Week", y=["Label agreement (%)", "Criterion agreement (%)"], y_label="%")

    st.markdown("#### Reviewed evaluations")
    st.dataframe(review_rows(agreement["rows"]), hide_index=True, width="stretch")


def share(agreed: int, out_of: int) -> int | None:
    return round(100 * agreed / out_of) if out_of else None


def percent(agreed: int, out_of: int) -> str:
    return "–" if not out_of else f"{share(agreed, out_of)} %"


def criterion_rows(criteria: dict) -> list[dict]:
    rows = [
        {
            "Criterion": criterion_name(name),
            "Checked": counts["checked"],
            "Agreement": share(counts["agreed"], counts["checked"]),
        }
        for name, counts in criteria.items()
    ]
    # never checked last: there is no agreement to show
    return sorted(rows, key=lambda row: (row["Agreement"] is None, row["Agreement"] or 0))


def week_rows(weeks: list[dict]) -> list[dict]:
    return [
        {
            "Week": week["week"],
            "Reviews": week["reviewed"],
            "Label agreement": percent(week["label_agreed"], week["reviewed"]),
            "Criteria checked": week["checked"],
            "Criterion agreement": percent(week["agreed"], week["checked"]),
        }
        for week in reversed(weeks)
    ]


def review_rows(rows: list[dict]) -> list[dict]:
    return [
        {
            "Class": f"{row['batch_id']} {date.fromisoformat(row['class_date']):%d/%m/%Y}",
            "Tutor": row["tutor"],
            "Suggested": row["label"],
            "QA": row["qa_label"],
            "Checked": len(row["checked"]),
            "Overridden": ", ".join(criterion_name(c) for c in row["overridden"]) or "none",
            "Reviewer": row["reviewer"],
            "Reviewed": ist(row["reviewed_at"]),
        }
        for row in reversed(rows)
    ]
