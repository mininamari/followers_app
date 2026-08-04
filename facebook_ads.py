from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from core.auth import has_permission
from core.config import DB_PATH, now_utc
from core.db import db_df
from core.i18n import tr
from core.style import hero
from integrations.facebook_ads_client import is_configured
from integrations.facebook_ads_sync import last_sync_for_account, sync_ad_account

FATIGUE_MIN_DAYS = 6
FATIGUE_DECLINE_RATIO = 0.7
MIN_ROWS_FOR_PERFORMANCE_FLAG = 4


def _save_account_mapping(account_id: str, label: str, novakid_account: str, is_active: bool) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO fb_ad_accounts(account_id, label, novakid_account, is_active, created_at)
            VALUES(?,?,?,?,?)
            ON CONFLICT(account_id) DO UPDATE SET
                label=excluded.label,
                novakid_account=excluded.novakid_account,
                is_active=excluded.is_active
            """,
            (account_id, label, novakid_account, int(is_active), now_utc()),
        )
        conn.commit()


def _save_creative_tags(df: pd.DataFrame) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        for _, row in df.iterrows():
            conn.execute(
                "UPDATE fb_creatives SET tags=? WHERE creative_id=?",
                (row["tags"] if pd.notna(row["tags"]) and str(row["tags"]).strip() else None, row["creative_id"]),
            )
        conn.commit()


def _ads_overview_df(account_ids: list[str]) -> pd.DataFrame:
    if not account_ids:
        return pd.DataFrame()
    placeholders = ",".join(["?"] * len(account_ids))
    query = f"""
        SELECT
            c.account_id,
            c.campaign_id,
            c.name AS campaign_name,
            c.objective,
            c.status AS campaign_status,
            a.ad_id,
            a.name AS ad_name,
            a.status AS ad_status,
            cr.creative_id,
            cr.title,
            cr.thumbnail_url,
            cr.tags,
            COALESCE(SUM(i.spend), 0) AS spend,
            COALESCE(SUM(i.impressions), 0) AS impressions,
            COALESCE(SUM(i.reach), 0) AS reach,
            COALESCE(SUM(i.clicks), 0) AS clicks
        FROM fb_campaigns c
        JOIN fb_ads a ON a.campaign_id = c.campaign_id
        LEFT JOIN fb_creatives cr ON cr.ad_id = a.ad_id
        LEFT JOIN fb_insights i ON i.ad_id = a.ad_id
        WHERE c.account_id IN ({placeholders})
        GROUP BY c.campaign_id, a.ad_id
        ORDER BY spend DESC
    """
    return db_df(query, account_ids)


def _attach_follower_match(df: pd.DataFrame) -> pd.DataFrame:
    """Best-effort join to manually uploaded followers, matched by ad name == publication id.

    This mirrors the existing Novakid PR matching in core.csv_import.import_pr, which
    already keys manual follower uploads by ad name. The real join key should be
    revisited once live Facebook ad names are visible in Sync.
    """
    if df.empty:
        df["matched_followers"] = None
        df["matched_cpf"] = None
        return df
    final_results = db_df(
        "SELECT publication_id, SUM(final_followers) AS matched_followers "
        "FROM final_results GROUP BY publication_id"
    )
    if final_results.empty:
        df["matched_followers"] = None
        df["matched_cpf"] = None
        return df
    merged = df.merge(final_results, left_on="ad_name", right_on="publication_id", how="left")
    merged["matched_cpf"] = merged.apply(
        lambda r: round(r["spend"] / r["matched_followers"], 4)
        if r.get("matched_followers") and r["matched_followers"] > 0
        else None,
        axis=1,
    )
    return merged.drop(columns=["publication_id"], errors="ignore")


def _fatigued_ad_ids(ad_ids: list[str]) -> set[str]:
    """Ads whose daily reach dropped off in the second half of their history.

    Mirrors the "creative fatigue" idea from Alison.ai's dashboard: a creative that
    used to reach people well but is tailing off, even if it's still spending.
    """
    if not ad_ids:
        return set()
    placeholders = ",".join(["?"] * len(ad_ids))
    daily = db_df(
        f"SELECT ad_id, date_start, reach FROM fb_insights WHERE ad_id IN ({placeholders}) ORDER BY ad_id, date_start",
        ad_ids,
    )
    if daily.empty:
        return set()
    fatigued: set[str] = set()
    for ad_id, group in daily.groupby("ad_id"):
        reach = group["reach"].tolist()
        if len(reach) < FATIGUE_MIN_DAYS:
            continue
        midpoint = len(reach) // 2
        early_avg = sum(reach[:midpoint]) / midpoint
        recent_avg = sum(reach[midpoint:]) / (len(reach) - midpoint)
        if early_avg > 0 and recent_avg < early_avg * FATIGUE_DECLINE_RATIO:
            fatigued.add(ad_id)
    return fatigued


def _add_performance_flags(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        df["ctr"] = None
        df["fatigue"] = ""
        df["performance_flag"] = ""
        return df

    df = df.copy()
    df["ctr"] = df.apply(
        lambda r: round(r["clicks"] / r["impressions"] * 100, 2) if r["impressions"] else None,
        axis=1,
    )

    fatigued = _fatigued_ad_ids(df["ad_id"].dropna().unique().tolist())
    df["fatigue"] = df["ad_id"].apply(lambda ad_id: "📉 Fatigue" if ad_id in fatigued else "")

    if len(df) >= MIN_ROWS_FOR_PERFORMANCE_FLAG and df["ctr"].notna().any():
        spend_threshold = df["spend"].quantile(0.75)
        ctr_threshold = df["ctr"].quantile(0.25)

        def _flag(row: pd.Series) -> str:
            if row["spend"] >= spend_threshold and pd.notna(row["ctr"]) and row["ctr"] <= ctr_threshold:
                return "⚠️ High spend, low CTR"
            return ""

        df["performance_flag"] = df.apply(_flag, axis=1)
    else:
        df["performance_flag"] = ""
    return df


def page_facebook_ads(user: dict) -> None:
    if not has_permission(user, "view_fb_ads"):
        st.error(tr("You do not have permission to view Facebook Ads.", "У вас нет прав для просмотра Facebook Ads."))
        return

    hero(
        "Facebook Ads",
        tr(
            "Campaigns, ads, creatives, and spend from the Facebook Marketing API matched with followers from manual Novakid PR uploads.",
            "Кампании, объявления, креативы и расходы из Facebook Marketing API, сопоставленные "
            "с подписчиками из ручных выгрузок Novakid PR.",
        ),
        ["Campaigns", "Creatives", "Spend", "Best-effort match"],
    )

    if not is_configured():
        st.warning(
            tr(
                "META_ACCESS_TOKEN is not configured. Sync is unavailable until a Facebook Marketing API system user token is created in Business Manager and added to environment variables.",
                "META_ACCESS_TOKEN не настроен. Синхронизация недоступна, пока не будет создан "
                "системный токен Facebook Marketing API (System User token в Business Manager) "
                "и добавлен в переменные окружения.",
            )
        )

    can_manage = has_permission(user, "manage_fb_ads")

    if can_manage:
        with st.expander(tr("Facebook Ad Accounts", "Рекламные аккаунты Facebook"), expanded=False):
            accounts_df = db_df("SELECT * FROM fb_ad_accounts ORDER BY label")
            if not accounts_df.empty:
                st.dataframe(accounts_df, use_container_width=True, hide_index=True)
            with st.form("fb_account_mapping"):
                st.caption(tr("Add a Facebook ad account and map it to a Novakid region.", "Добавьте рекламный аккаунт Facebook и свяжите его с регионом Novakid."))
                account_id = st.text_input(tr("Ad account ID", "ID рекламного аккаунта"), placeholder="act_1234567890")
                label = st.text_input(tr("Label", "Название"), placeholder="Israel")
                novakid_account = st.text_input(tr("Novakid account", "Аккаунт Novakid"), placeholder="novakid_israel")
                is_active = st.checkbox(tr("Active", "Активен"), value=True)
                submitted = st.form_submit_button(tr("Save", "Сохранить"), use_container_width=True)
            if submitted:
                if not account_id.strip().startswith("act_"):
                    st.error(tr("Ad account ID must start with act_.", "ID рекламного аккаунта должен начинаться с act_."))
                else:
                    _save_account_mapping(account_id.strip(), label.strip(), novakid_account.strip(), is_active)
                    st.success(tr("Saved.", "Сохранено."))
                    st.rerun()

    accounts_df = db_df("SELECT * FROM fb_ad_accounts WHERE is_active=1 ORDER BY label")
    if accounts_df.empty:
        st.info(tr("Add a Facebook ad account to start syncing.", "Добавьте рекламный аккаунт Facebook, чтобы начать синхронизацию."))
        return

    if can_manage:
        st.markdown("### " + tr("Sync", "Синхронизация"))
        for _, row in accounts_df.iterrows():
            col1, col2 = st.columns([3, 1])
            last_sync = last_sync_for_account(row["account_id"])
            status_text = (
                tr("not synced yet", "ещё не синхронизировано") if not last_sync else f"{last_sync['status']} — {last_sync['started_at']}"
            )
            col1.write(f"**{row['label'] or row['account_id']}** ({row['account_id']}) — {status_text}")
            if col2.button(
                "Sync now",
                key=f"sync_{row['account_id']}",
                disabled=not is_configured(),
                use_container_width=True,
            ):
                with st.spinner(tr("Syncing...", "Синхронизация...")):
                    result = sync_ad_account(row["account_id"])
                if result.status == "ok":
                    st.success(result.message)
                else:
                    st.error(result.message)
                st.rerun()

    st.markdown("### " + tr("Campaigns And Ads", "Кампании и объявления"))
    overview = _ads_overview_df(accounts_df["account_id"].tolist())
    overview = _attach_follower_match(overview)
    if overview.empty:
        st.info(tr("No data yet. Run sync above.", "Пока нет данных. Запустите синхронизацию выше."))
        return

    overview = _add_performance_flags(overview)
    overview_full = overview

    sort_options = {
        "Spend": "spend",
        "Reach": "reach",
        "CTR": "ctr",
        "Matched followers": "matched_followers",
        tr("Matched CPF (lower is better)", "Matched CPF (ниже — лучше)"): "matched_cpf",
    }
    filter_col, sort_col = st.columns([2, 1])
    view_filter = filter_col.radio(
        tr("Show", "Показать"),
        [tr("All", "Все"), "Top spend", "Fatigue", "High spend / low CTR"],
        horizontal=True,
    )
    sort_label = sort_col.selectbox(tr("Sort by", "Сортировать по"), list(sort_options.keys()))

    if view_filter == "Top spend":
        overview = overview.sort_values("spend", ascending=False).head(10)
    elif view_filter == "Fatigue":
        overview = overview[overview["fatigue"] != ""]
    elif view_filter == "High spend / low CTR":
        overview = overview[overview["performance_flag"] != ""]

    sort_key = sort_options[sort_label]
    overview = overview.sort_values(sort_key, ascending=(sort_key == "matched_cpf"), na_position="last")

    if overview.empty:
        st.info(tr("No ads match the selected filter.", "Нет объявлений под выбранный фильтр."))
    else:
        display_cols = [
            "campaign_name", "ad_name", "ad_status", "thumbnail_url", "spend", "impressions",
            "reach", "ctr", "fatigue", "performance_flag", "matched_followers", "matched_cpf", "tags",
        ]
        st.dataframe(
            overview[display_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "campaign_name": tr("Campaign", "Кампания"),
                "ad_name": tr("Ad", "Объявление"),
                "ad_status": tr("Status", "Статус"),
                "thumbnail_url": st.column_config.ImageColumn("Creative"),
                "spend": st.column_config.NumberColumn("Spend, USD", format="$%.2f"),
                "ctr": st.column_config.NumberColumn("CTR, %", format="%.2f%%"),
                "fatigue": "",
                "performance_flag": "",
                "matched_followers": tr("Followers (matched)", "Подписчики (matched)"),
                "matched_cpf": st.column_config.NumberColumn("CPF (matched), USD", format="$%.2f"),
                "tags": tr("Tags", "Теги"),
            },
        )

    st.markdown("### " + tr("Creative Tags", "Теги креативов"))
    st.caption(
        tr(
            "Free-form tags, for example carousel, UGC, testimonial, will help select the best creatives for a targeting presentation later.",
            "Свободные теги (например: carousel, UGC, testimonial) — пригодятся позже для отбора "
            "лучших креативов в презентацию для таргетолога.",
        )
    )
    taggable = (
        overview_full[overview_full["creative_id"].notna()][["creative_id", "ad_name", "title", "tags"]]
        .drop_duplicates("creative_id")
    )
    if taggable.empty:
        st.info(tr("No creatives linked to ads yet.", "Пока нет креативов с привязкой к объявлению."))
    else:
        edited_tags = st.data_editor(
            taggable,
            use_container_width=True,
            hide_index=True,
            disabled=["creative_id", "ad_name", "title"],
            column_config={
                "creative_id": None,
                "ad_name": tr("Ad", "Объявление"),
                "title": tr("Creative title", "Заголовок креатива"),
                "tags": st.column_config.TextColumn(tr("Tags", "Теги"), help=tr("Comma separated", "Через запятую")),
            },
            key="fb_creative_tags_editor",
        )
        if st.button(tr("Save tags", "Сохранить теги"), use_container_width=True):
            _save_creative_tags(edited_tags)
            st.success(tr("Tags saved.", "Теги сохранены."))
            st.rerun()
