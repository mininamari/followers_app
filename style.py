from __future__ import annotations

import streamlit as st

NOVAKID_CSS = """
<style>
:root {
    --nk-purple: #6D3DF5;
    --nk-purple-dark: #4E2AC8;
    --nk-blue: #00A6FF;
    --nk-green: #53D86A;
    --nk-yellow: #FFD84D;
    --nk-pink: #FF6FAE;
    --nk-orange: #FF9F2E;
    --nk-bg: #F7F4FF;
    --nk-card: #FFFFFF;
    --nk-ink: #1D2142;
    --nk-muted: #6E7191;
    --nk-border: rgba(109, 61, 245, .14);
}
.stApp {
    background:
        radial-gradient(circle at 8% 8%, rgba(255,216,77,.28) 0, rgba(255,216,77,0) 26%),
        radial-gradient(circle at 90% 4%, rgba(0,166,255,.18) 0, rgba(0,166,255,0) 24%),
        linear-gradient(180deg, #FAF8FF 0%, #F3F6FF 100%);
    color: var(--nk-ink);
}
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #6D3DF5 0%, #4E2AC8 100%);
}
[data-testid="stSidebar"] * { color: #fff !important; }
[data-testid="stSidebar"] [role="radiogroup"] label {
    border-radius: 16px;
    padding: 8px 10px;
    margin-bottom: 4px;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background: rgba(255,255,255,.12);
}
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1280px; }
h1, h2, h3 { color: var(--nk-ink); letter-spacing: -0.03em; }
.nk-hero {
    background: linear-gradient(135deg, #6D3DF5 0%, #7B61FF 48%, #00A6FF 100%);
    border-radius: 34px;
    padding: 28px 32px;
    color: white;
    box-shadow: 0 18px 50px rgba(78,42,200,.24);
    position: relative;
    overflow: hidden;
    margin-bottom: 22px;
}
.nk-hero:before {
    content: "";
    position: absolute;
    width: 180px; height: 180px;
    background: rgba(255,216,77,.9);
    border-radius: 50%;
    right: -60px; top: -60px;
}
.nk-hero:after {
    content: "★";
    position: absolute;
    right: 76px; bottom: 26px;
    color: #FFD84D;
    font-size: 42px;
    transform: rotate(12deg);
}
.nk-hero h1 { color: white; margin: 0; font-size: 2.25rem; }
.nk-hero p { color: rgba(255,255,255,.88); margin: 8px 0 0 0; font-size: 1.02rem; max-width: 760px; }
.nk-chip-row { display:flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.nk-chip {
    background: rgba(255,255,255,.16);
    border: 1px solid rgba(255,255,255,.20);
    border-radius: 999px;
    padding: 7px 12px;
    color: #fff;
    font-weight: 700;
    font-size: .86rem;
}
.nk-card {
    background: rgba(255,255,255,.88);
    border: 1px solid var(--nk-border);
    border-radius: 26px;
    padding: 20px;
    box-shadow: 0 14px 36px rgba(58,53,123,.08);
    margin-bottom: 16px;
}
.nk-small-card {
    background: white;
    border: 1px solid var(--nk-border);
    border-radius: 22px;
    padding: 16px 18px;
    box-shadow: 0 12px 30px rgba(58,53,123,.07);
}
.nk-label { color: var(--nk-muted); font-size: .86rem; font-weight: 800; text-transform: uppercase; letter-spacing: .04em; }
.nk-value { color: var(--nk-ink); font-size: 1.8rem; line-height: 1.15; font-weight: 900; margin-top: 4px; }
.nk-help { color: var(--nk-muted); font-size: .92rem; margin-top: 6px; }
div.stButton > button, div.stDownloadButton > button {
    border-radius: 999px !important;
    border: 0 !important;
    background: linear-gradient(135deg, #FF9F2E 0%, #FFD84D 100%) !important;
    color: #291B5B !important;
    font-weight: 900 !important;
    box-shadow: 0 10px 26px rgba(255,159,46,.26) !important;
}
[data-testid="stMetric"] {
    background: #fff;
    border: 1px solid var(--nk-border);
    border-radius: 24px;
    padding: 14px 16px;
    box-shadow: 0 12px 30px rgba(58,53,123,.07);
}
[data-testid="stMetricLabel"] { color: var(--nk-muted); font-weight: 800; }
[data-testid="stMetricValue"] { color: var(--nk-ink); font-weight: 900; }
.stDataFrame, [data-testid="stDataFrame"] {
    border-radius: 22px;
    overflow: hidden;
}
.nk-status-ok { color: #188038; font-weight: 800; }
.nk-status-warn { color: #B06000; font-weight: 800; }
</style>
"""


def apply_novakid_style() -> None:
    st.markdown(NOVAKID_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str, chips: list[str] | None = None) -> None:
    chip_html = "" if not chips else "<div class='nk-chip-row'>" + "".join([f"<span class='nk-chip'>{c}</span>" for c in chips]) + "</div>"
    st.markdown(
        f"""
        <div class="nk-hero">
            <h1>{title}</h1>
            <p>{subtitle}</p>
            {chip_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_card(title: str, text: str = "") -> None:
    st.markdown(
        f"""
        <div class="nk-card">
            <div class="nk-label">{title}</div>
            {f'<div class="nk-help">{text}</div>' if text else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )
