import os

import requests
import streamlit as st

# the frontend gets only these two from its environment; it never sees the DB URL or the Anthropic key
API_URL = os.environ.get("API_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")


def call_api(method: str, path: str, timeout: float = 30, **kwargs) -> requests.Response:
    """Stops the page with a clear message when the API is unreachable or rejects the key."""
    try:
        response = requests.request(
            method, f"{API_URL}{path}", headers={"X-API-Key": API_KEY}, timeout=timeout, **kwargs
        )
    except requests.RequestException:
        st.error(
            f"Cannot reach the Humaniti AI API at {API_URL}. Check that it is running "
            "(`docker compose ps`) and try again."
        )
        st.stop()
    if response.status_code == 401:
        st.error("The API rejected the key. The frontend and the API need the same API_KEY.")
        st.stop()
    return response


def detail(response: requests.Response) -> str:
    try:
        message = response.json()["detail"]
    except (ValueError, KeyError):
        return f"The API answered {response.status_code}."
    if isinstance(message, list):
        return "; ".join(f"{error['loc'][-1]}: {error['msg']}" for error in message)
    return message
