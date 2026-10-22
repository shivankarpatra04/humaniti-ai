import re
from datetime import UTC, date, datetime

import report
import streamlit as st
from agreement import agreement_page
from api import call_api, detail
from history import tutor_history

POLL_S = 5
LEVELS = ["Beginner", "Intermediate", "Advanced"]
STAGES = {
    "queued": "Waiting for the worker",
    "downloading": "Downloading the link",
    "extracting": "Extracting audio and frames",
    "transcribing": "Transcribing (the longest step)",
    "video_facts": "Checking background, camera and lighting",
    "audio_metrics": "Measuring audio",
    "llm": "Claude is rating the class",
    "saving": "Saving the result",
}


def from_file_name(name: str) -> dict:
    """Same loose parsing as the API's ingest.parse_file_name; the frontend cannot import app code."""
    batch = re.search(r"(?<![a-z0-9])b\d+", name, re.IGNORECASE)
    level = re.search(r"beginner|intermediate|advanced", name, re.IGNORECASE)
    class_date = re.search(r"\d{4}-\d{2}-\d{2}", name)
    return {
        "batch_id": batch.group().upper() if batch else "",
        "level": level.group().title() if level else None,
        "class_date": date.fromisoformat(class_date.group()) if class_date else None,
    }


def new_evaluation() -> None:
    evaluation_id = st.query_params.get("id")
    if evaluation_id:
        show_evaluation(int(evaluation_id))
        if st.button("Evaluate another class"):
            st.query_params.clear()
            st.rerun()
        return

    st.title("New evaluation")
    source = st.radio("Class recording", ["Upload a file", "Link"], horizontal=True)
    video = url = None
    if source == "Upload a file":
        video = st.file_uploader("Video (mp4, mkv or webm)", type=["mp4", "mkv", "webm"])
    else:
        url = st.text_input("Link to the recording", placeholder="https://...")
    # widgets without keys reset to the new defaults whenever another file is chosen
    defaults = from_file_name(video.name) if video else {}

    with st.form("class"):
        tutor_name = st.text_input("Tutor name *", placeholder="Demo Tutor")
        left, middle, right = st.columns(3)
        batch_id = left.text_input("Batch *", value=defaults.get("batch_id", ""), placeholder="B435")
        class_date = middle.date_input("Class date *", value=defaults.get("class_date"), format="DD/MM/YYYY")
        level = defaults.get("level")
        level = right.selectbox("Level *", LEVELS, index=LEVELS.index(level) if level else None)
        if not st.form_submit_button("Evaluate", type="primary"):
            return

    form = {"tutor_name": tutor_name.strip(), "batch_id": batch_id.strip(), "class_date": class_date}
    form["level"] = level
    missing = [name for name, value in form.items() if not value]
    if video is None and not (url or "").strip():
        missing.insert(0, "video file" if source == "Upload a file" else "link")
    if missing:
        st.error(f"Please fill in: {', '.join(missing)}.")
        return
    form["class_date"] = class_date.isoformat()
    if video:
        with st.spinner(f"Uploading {video.name} ..."):
            files = {"file": (video.name, video.getvalue(), video.type or "video/mp4")}
            response = call_api("POST", "/evaluations", data=form, files=files, timeout=600)
    else:
        response = call_api("POST", "/evaluations", data={**form, "url": url.strip()})
    if not response.ok:
        st.error(detail(response))
        return
    st.query_params["id"] = str(response.json()["id"])
    st.rerun()


def fetch_evaluation(evaluation_id: int) -> dict | None:
    response = call_api("GET", f"/evaluations/{evaluation_id}")
    if response.ok:
        return response.json()
    st.error(detail(response))
    return None


def show_evaluation(evaluation_id: int) -> None:
    evaluation = fetch_evaluation(evaluation_id)
    if evaluation is None:
        return
    if evaluation["status"] in ("pending", "processing"):
        live_progress(evaluation_id)
    elif evaluation["status"] == "failed":
        st.title(f"{evaluation['batch_id']} | {evaluation['tutor']}")
        st.error(f"**The evaluation failed.** {evaluation['error']}")
        st.info(
            "Fix the cause, then send the same file or link again; finished steps such as the transcript "
            "are reused."
        )
    else:
        transcript = call_api("GET", f"/evaluations/{evaluation_id}/transcript")
        report.show(evaluation, transcript.json() if transcript.ok else None)


@st.fragment(run_every=POLL_S)
def live_progress(evaluation_id: int) -> None:
    evaluation = fetch_evaluation(evaluation_id)
    if evaluation is None:
        return
    if evaluation["status"] not in ("pending", "processing"):
        st.rerun()
    st.title(f"{evaluation['batch_id']} | {evaluation['tutor']}")
    stage = evaluation["stage"] if evaluation["stage"] in STAGES else "queued"
    step = list(STAGES).index(stage) + 1
    elapsed = int((datetime.now(UTC) - datetime.fromisoformat(evaluation["created_at"])).total_seconds())
    text = f"Step {step} of {len(STAGES)}: {STAGES[stage]} · {elapsed // 60} min {elapsed % 60:02d} s elapsed"
    st.progress(step / (len(STAGES) + 1), text=text)
    st.caption(
        f"Updates every {POLL_S} s. A 45-minute class takes about 10 minutes, most of it transcription. "
        "You can leave and come back: this page's address keeps the evaluation."
    )


st.set_page_config(page_title="Humaniti AI", page_icon="♟️", layout="wide")
page = st.navigation(
    [
        st.Page(new_evaluation, title="New evaluation", icon=":material/upload_file:", default=True),
        st.Page(tutor_history, title="Tutor history", icon=":material/history:", url_path="history"),
        st.Page(agreement_page, title="Agreement", icon=":material/fact_check:", url_path="agreement"),
    ]
)
st.sidebar.markdown("**Humaniti AI**  \nClass quality reviews for Eight Times Eight")
page.run()
