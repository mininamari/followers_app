from __future__ import annotations

import streamlit as st


LANGUAGE_OPTIONS = {
    "English": "en",
    "Русский": "ru",
}
LANGUAGE_LABELS = {value: label for label, value in LANGUAGE_OPTIONS.items()}
DEFAULT_LANGUAGE = "en"


def current_language() -> str:
    return st.session_state.get("language", DEFAULT_LANGUAGE)


def set_language_from_label(label: str) -> None:
    st.session_state["language"] = LANGUAGE_OPTIONS.get(label, DEFAULT_LANGUAGE)


def tr(en: str, ru: str) -> str:
    return ru if current_language() == "ru" else en
