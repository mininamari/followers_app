from __future__ import annotations

import plotly.express as px
import streamlit as st

from core.auth import has_permission
from core.csv_import import latest_publications_df, monthly_increment_df
from core.db import db_df
from core.i18n import tr
from core.style import hero
from screens._shared import apply_date_filter, shared_results_filters


def page_dashboard() -> None:
    user = st.session_state.get("user")
    if not has_permission(user, "view_dashboard"):
        st.error(tr("You do not have permission to view the Dashboard.", "У вас нет прав для просмотра Dashboard."))
        return
    hero(
        "Dashboard",
        tr(
            "Overview of followers, spend, and CPF across Novakid regions. Use filters to focus on specific accounts or months.",
            "Обзор подписчиков, затрат и CPF по всем регионам Novakid. Используйте фильтры, чтобы смотреть отдельные аккаунты или месяцы.",
        ),
        ["Followers", "Spend", "CPF", "Warnings"],
    )
    df = db_df("SELECT * FROM final_results ORDER BY period_start DESC, account, final_followers DESC")
    if df.empty:
        st.info(tr("No data yet. Upload a Meta CSV first, then a PR CSV if available.", "Пока нет данных. Загрузите Meta CSV, затем PR CSV при наличии."))
        return

    selected_accounts, selected_periods, only_warnings = shared_results_filters(df)

    base = df[df["account"].isin(selected_accounts)] if selected_accounts else df.iloc[0:0]
    base = latest_publications_df(base)
    if only_warnings:
        base = base[base["warning"].fillna("") != ""]

    f = apply_date_filter(base, selected_periods)

    total_followers = int(f["final_followers"].sum()) if not f.empty else 0
    total_meta = int(f["meta_followers"].sum()) if not f.empty else 0
    total_pr = int(f["pr_followers"].sum()) if not f.empty else 0
    total_spend = float(f["spend_usd"].sum()) if not f.empty else 0.0
    cpf = total_spend / total_pr if total_pr > 0 else None
    warning_count = int((f["warning"].fillna("") != "").sum()) if not f.empty else 0

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Final followers", f"{total_followers:,}")
    m2.metric("Meta followers", f"{total_meta:,}")
    m3.metric("PR followers", f"{total_pr:,}")
    m4.metric("Spend", f"${total_spend:,.2f}")
    m5.metric("CPF", "—" if cpf is None else f"${cpf:,.2f}")

    if warning_count:
        st.warning(tr(f"Rows need review: {warning_count}", f"Есть строки для проверки: {warning_count}"))

    if not f.empty:
        c1, c2 = st.columns([1.25, 1])
        with c1:
            monthly = monthly_increment_df(base)
            monthly = apply_date_filter(monthly, selected_periods)
            fig = px.bar(
                monthly.sort_values(["month", "account"]),
                x="month_label",
                y="monthly_followers",
                color="account",
                title="Followers by month",
                labels={"month_label": "Month", "monthly_followers": "Followers"},
            )
            fig.update_layout(
                template="plotly_white",
                title_font_size=20,
                legend_title_text="Account",
                xaxis_title="Month",
                yaxis_title="Followers",
                bargap=0.28,
            )
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            by_account = f.groupby("account", as_index=False).agg(final_followers=("final_followers", "sum"), spend_usd=("spend_usd", "sum"))
            fig2 = px.bar(by_account.sort_values("final_followers", ascending=False), x="account", y="final_followers", title="Followers by account")
            fig2.update_layout(template="plotly_white", title_font_size=20, xaxis_title="", yaxis_title="Followers")
            st.plotly_chart(fig2, use_container_width=True)

        st.markdown("### " + tr("Top Publications", "Топ публикаций"))
        top = f.sort_values("final_followers", ascending=False).head(12)
        st.dataframe(
            top[["account", "month", "publication_id", "publication_link", "final_followers", "spend_usd", "cpf_usd", "warning"]],
            use_container_width=True,
            hide_index=True,
            column_config={"publication_link": st.column_config.LinkColumn("Link")},
        )
