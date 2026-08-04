from __future__ import annotations

import sqlite3

import streamlit as st

from core.auth import get_user, hash_password, verify_password
from core.config import DB_PATH
from core.i18n import tr
from core.style import hero


def page_profile(user: dict) -> None:
    hero("Profile", tr("Change your personal user password.", "Смена личного пароля пользователя."), ["Security"])
    with st.form("change_my_password"):
        old = st.text_input(tr("Current password", "Старый пароль"), type="password")
        new = st.text_input(tr("New password", "Новый пароль"), type="password")
        ok = st.form_submit_button(tr("Change password", "Сменить пароль"), use_container_width=True)
    if ok:
        current = get_user(user["username"])
        if current and verify_password(old, current["password_hash"]) and len(new) >= 8:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("UPDATE users SET password_hash=? WHERE username=?", (hash_password(new), user["username"]))
                conn.commit()
            st.success(tr("Password updated.", "Пароль обновлен."))
        else:
            st.error(tr("Check your current password. The new password must be at least 8 characters.", "Проверьте старый пароль. Новый пароль должен быть минимум 8 символов."))
