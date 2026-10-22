"""The recording in the report, and buttons that start it at an evidence timestamp."""

import re
import time

import streamlit as st
from api import call_api, detail

TIMESTAMP = re.compile(r"(?<!\d)(\d{1,3}):([0-5]\d)(?!\d)")
MAX_BUTTONS = 3
# a new link changes the player's source and reloads it, so one is fetched only when this close to expiry
RENEW_BEFORE_S = 120


def video_url(evaluation_id: int) -> str | None:
    """A signed link the browser streams from the API; the video never passes through Streamlit."""
    key = f"video_url_{evaluation_id}"
    link = st.session_state.get(key)
    if link and link["expires"] - time.time() > RENEW_BEFORE_S:
        return link["url"]
    response = call_api("GET", f"/evaluations/{evaluation_id}/video-url")
    if not response.ok:
        st.info(detail(response))
        return None
    st.session_state[key] = response.json()
    return st.session_state[key]["url"]


def show(evaluation_id: int) -> None:
    url = video_url(evaluation_id)
    if url is None:
        return
    start = st.session_state.get(f"start_{evaluation_id}", 0)
    st.video(url, start_time=start, autoplay=start > 0)


def seconds(text: str) -> list[int]:
    """Distinct mm:ss timestamps in the order they appear."""
    found = [int(minutes) * 60 + int(secs) for minutes, secs in TIMESTAMP.findall(text)]
    return list(dict.fromkeys(found))


def mmss(second: float) -> str:
    return f"{int(second) // 60:02d}:{int(second) % 60:02d}"


def seek_buttons(evaluation_id: int, text: str, key: str) -> None:
    for second in seconds(text)[:MAX_BUTTONS]:
        st.button(
            f"▶ {mmss(second)}",
            key=f"{key}_{second}",
            on_click=st.session_state.__setitem__,
            args=(f"start_{evaluation_id}", second),
            type="tertiary",
        )
