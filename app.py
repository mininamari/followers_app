from __future__ import annotations

import streamlit as st

from core.auth import authenticate, has_permission
from core.config import ROLE_LABELS
from core.db import db_df, init_db
from core.i18n import LANGUAGE_LABELS, LANGUAGE_OPTIONS, current_language, set_language_from_label, tr
from core.style import apply_novakid_style, hero
from screens.backups import page_backups
from screens.dashboard import page_dashboard
from screens.facebook_ads import page_facebook_ads
from screens.history import page_upload_history
from screens.profile import page_profile
from screens.reports import page_report
from screens.upload_meta import page_upload_meta
from screens.upload_pr import page_upload_pr
from screens.users import page_users


def login_screen() -> None:
    st.set_page_config(page_title="Novakid Social Reports", layout="wide", page_icon="⭐")
    apply_novakid_style()
    left, mid, right = st.columns([1, 1.25, 1])
    with mid:
        language_label = LANGUAGE_LABELS.get(current_language(), "English")
        st.selectbox(
            tr("Language", "Язык"),
            list(LANGUAGE_OPTIONS.keys()),
            index=list(LANGUAGE_OPTIONS.keys()).index(language_label),
            on_change=lambda: set_language_from_label(st.session_state["login_language"]),
            key="login_language",
        )
        hero(
            "Novakid Social Reports",
            tr(
                "Sign in to upload Meta and PR CSV files, calculate followers, and monitor CPF by region.",
                "Войдите, чтобы загружать Meta и PR CSV, считать подписчиков и следить за CPF по регионам.",
            ),
            ["Meta + PR", "Regions", "CPF", "Team access"],
        )
        with st.form("login"):
            st.markdown("### " + tr("Team Login", "Вход в командный кабинет"))
            username = st.text_input(tr("Username", "Логин"))
            password = st.text_input(tr("Password", "Пароль"), type="password")
            submitted = st.form_submit_button(tr("Sign in", "Войти"), type="primary", use_container_width=True)
        if submitted:
            user = authenticate(username, password)
            if user:
                st.session_state["user"] = {"username": user["username"], "role": user["role"]}
                st.rerun()
            else:
                st.error(tr("Incorrect username or password.", "Неверный логин или пароль."))
        if db_df("SELECT COUNT(*) AS user_count FROM users")["user_count"].iloc[0] == 0:
            st.warning(tr(
                "No users have been created yet. The first admin is configured through environment variables.",
                "Пользователи еще не созданы. Администратор первого запуска задается через переменные окружения.",
            ))


def require_login() -> dict:
    if "user" not in st.session_state:
        login_screen()
        st.stop()
    return st.session_state["user"]


def sidebar(user: dict) -> str:
    with st.sidebar:
        st.markdown("# ⭐ Novakid")
        st.caption("Social Reports")
        language_label = LANGUAGE_LABELS.get(current_language(), "English")
        st.selectbox(
            tr("Language", "Язык"),
            list(LANGUAGE_OPTIONS.keys()),
            index=list(LANGUAGE_OPTIONS.keys()).index(language_label),
            on_change=lambda: set_language_from_label(st.session_state["sidebar_language"]),
            key="sidebar_language",
        )
        st.divider()
        st.write(f"**{user['username']}**")
        st.caption(f"{tr('role', 'роль')}: {ROLE_LABELS.get(user['role'], user['role'])}")
        pages = []
        if has_permission(user, "view_dashboard"):
            pages.append(("Dashboard", "Dashboard"))
        if has_permission(user, "upload_meta"):
            pages.append(("Upload Meta", tr("Upload Meta", "Загрузка Meta")))
        if has_permission(user, "upload_pr"):
            pages.append(("Upload PR", tr("Upload PR", "Загрузка PR")))
        if has_permission(user, "view_reports"):
            pages.append(("Reports", tr("Reports", "Отчеты")))
        if has_permission(user, "view_fb_ads"):
            pages.append(("Facebook Ads", "Facebook Ads"))
        if has_permission(user, "view_history"):
            pages.append(("Upload history", tr("Upload history", "История загрузок")))
        if has_permission(user, "manage_users"):
            pages.append(("Users", tr("Users", "Пользователи")))
        if has_permission(user, "manage_backups"):
            pages.append(("Backups", tr("Backups", "Резервные копии")))
        pages.append(("Profile", tr("Profile", "Профиль")))
        page_ids = [page_id for page_id, _ in pages]
        page_labels = dict(pages)
        page = st.radio(
            tr("Navigation", "Навигация"),
            page_ids,
            format_func=lambda page_id: page_labels[page_id],
            label_visibility="collapsed",
        )
        st.divider()
        if st.button(tr("Log out", "Выйти"), use_container_width=True):
            st.session_state.pop("user", None)
            st.rerun()
    return page


def main() -> None:
    init_db()
    user = require_login()
    st.set_page_config(page_title="Novakid Social Reports", layout="wide", page_icon="⭐")
    apply_novakid_style()
    page = sidebar(user)
    if page == "Dashboard":
        page_dashboard()
    elif page == "Upload Meta":
        page_upload_meta(user)
    elif page == "Upload PR":
        page_upload_pr(user)
    elif page == "Reports":
        page_report(user)
    elif page == "Facebook Ads":
        page_facebook_ads(user)
    elif page == "Upload history":
        page_upload_history()
    elif page == "Users":
        page_users(user)
    elif page == "Backups":
        page_backups(user)
    elif page == "Profile":
        page_profile(user)
    else:
        page_dashboard()


if __name__ == "__main__":
    main()
