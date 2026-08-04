from __future__ import annotations

import pandas as pd
import streamlit as st

from core.config import MONTH_NAMES
from core.csv_import import latest_publications_df
from core.db import db_df
from core.i18n import tr


def remember_shared_filter(widget_key: str, state_key: str) -> None:
    st.session_state[state_key] = st.session_state[widget_key]


def set_period_picker_year(year: str) -> None:
    st.session_state["period_picker_year"] = year


def toggle_period(period: str) -> None:
    selected_periods = list(st.session_state.get("filter_periods", []))
    if period in selected_periods:
        selected_periods.remove(period)
    else:
        selected_periods.append(period)
    st.session_state["filter_periods"] = sorted(selected_periods, reverse=True)
    st.session_state["period_picker_year"] = period[:4]


def clear_periods() -> None:
    st.session_state["filter_periods"] = []


def apply_date_filter(df: pd.DataFrame, selected_periods: list[str]) -> pd.DataFrame:
    if not selected_periods:
        return df.iloc[0:0]
    return df[df["month"].isin(selected_periods)]


def period_picker(container, available_periods: list[str]) -> list[str]:
    years = sorted({period[:4] for period in available_periods})
    selected_periods = st.session_state["filter_periods"]
    if not years:
        container.button(tr("Periods: Choose periods", "Периоды: выберите периоды"), disabled=True, use_container_width=True)
        return []

    if "period_picker_year" not in st.session_state or st.session_state["period_picker_year"] not in years:
        st.session_state["period_picker_year"] = selected_periods[0][:4] if selected_periods else years[-1]

    if len(selected_periods) == 1:
        selected_period = selected_periods[0]
        selected_label = f"{MONTH_NAMES[selected_period[5:7]]} {selected_period[:4]}"
    elif selected_periods:
        selected_label = tr(f"{len(selected_periods)} periods", f"{len(selected_periods)} периодов")
    else:
        selected_label = tr("Choose periods", "Выберите периоды")

    with container.popover(f"{tr('Periods', 'Периоды')}: {selected_label}", use_container_width=True):
        picker_year = st.session_state["period_picker_year"]
        year_index = years.index(picker_year)
        prev_col, year_col, next_col = st.columns([1, 2, 1])
        prev_col.button(
            "‹",
            key="period_previous_year",
            disabled=year_index == 0,
            on_click=set_period_picker_year,
            args=(years[max(0, year_index - 1)],),
            use_container_width=True,
        )
        year_col.markdown(f"<h4 style='text-align:center;margin:6px 0'>{picker_year}</h4>", unsafe_allow_html=True)
        next_col.button(
            "›",
            key="period_next_year",
            disabled=year_index == len(years) - 1,
            on_click=set_period_picker_year,
            args=(years[min(len(years) - 1, year_index + 1)],),
            use_container_width=True,
        )

        month_columns = st.columns(3)
        for index, (month_number, month_name) in enumerate(MONTH_NAMES.items()):
            period = f"{picker_year}-{month_number}"
            month_columns[index % 3].button(
                f"✓ {month_name}" if period in selected_periods else month_name,
                key=f"period_{period}",
                disabled=period not in available_periods,
                on_click=toggle_period,
                args=(period,),
                use_container_width=True,
            )
        st.button(
            tr("Clear periods", "Очистить периоды"),
            key="clear_period",
            disabled=not selected_periods,
            on_click=clear_periods,
            use_container_width=True,
        )
    return st.session_state["filter_periods"]


def shared_results_filters(df: pd.DataFrame) -> tuple[list[str], list[str], bool]:
    accounts = sorted(df["account"].dropna().unique().tolist())
    available_periods = sorted(df["month"].dropna().astype(str).unique().tolist(), reverse=True)
    defaults = {
        "filter_accounts": [],
        "filter_periods": [],
        "filter_warnings": False,
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default

    legacy_period = st.session_state.pop("filter_period", None)
    if legacy_period:
        if not st.session_state["filter_periods"]:
            st.session_state["filter_periods"] = [legacy_period]

    st.session_state["filter_accounts"] = [
        account for account in st.session_state["filter_accounts"] if account in accounts
    ]
    st.session_state["filter_periods"] = [
        period for period in st.session_state["filter_periods"] if period in available_periods
    ]

    st.session_state["_filter_accounts"] = st.session_state["filter_accounts"]
    st.session_state["_filter_warnings"] = st.session_state["filter_warnings"]

    c1, c2, c3 = st.columns([1.3, 1.1, .9])
    selected_accounts = c1.multiselect(
        tr("Region / account", "Регион / аккаунт"),
        accounts,
        key="_filter_accounts",
        on_change=remember_shared_filter,
        args=("_filter_accounts", "filter_accounts"),
    )
    selected_periods = period_picker(c2, available_periods)
    only_warnings = c3.checkbox(
        tr("Only warnings", "Только предупреждения"),
        key="_filter_warnings",
        on_change=remember_shared_filter,
        args=("_filter_warnings", "filter_warnings"),
    )
    return selected_accounts, selected_periods, only_warnings


def filtered_results_ui() -> pd.DataFrame:
    df = db_df("SELECT * FROM final_results ORDER BY period_start DESC, account, final_followers DESC")
    if df.empty:
        return df
    selected_accounts, selected_periods, only_warnings = shared_results_filters(df)
    f = df[df["account"].isin(selected_accounts)] if selected_accounts else df.iloc[0:0]
    f = latest_publications_df(f)
    f = apply_date_filter(f, selected_periods)
    if only_warnings:
        f = f[f["warning"].fillna("") != ""]
    return f
