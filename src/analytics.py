"""Settings for the streamlit_analytics2 tracking shared by the calculator and result pages."""

import os
from pathlib import Path

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

# Saved under data/ so that the Docker volume mounted there also persists the analytics events.
ANALYTICS_FILE: Path = Path(__file__).parent.parent / "data" / "analytics.db"


def analytics_password() -> str | None:
    """Password for the analytics dashboard, from the ANALYTICS_PASSWORD environment variable, falling back to
    "analytics_password" in Streamlit secrets.

    Returns None if neither is set, which leaves the dashboard without a password. An empty string must not be returned
    instead, as streamlit_analytics2 would then accept an empty password input.
    """
    password: str | None = os.environ.get("ANALYTICS_PASSWORD")
    if password:
        return password
    try:
        secret: object = st.secrets.get("analytics_password")
    except StreamlitSecretNotFoundError:
        return None
    return str(secret) if secret else None


def simple_analytics_embed() -> None:
    st.html(
        '<script async src="https://scripts.simpleanalyticscdn.com/latest.js"></script>', unsafe_allow_javascript=True
    )
