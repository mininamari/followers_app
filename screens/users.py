from __future__ import annotations

import sqlite3

import streamlit as st

from core.auth import get_user, has_permission, hash_password
from core.config import DB_PATH, ROLE_LABELS, ROLE_VIEWER, ROLES, now_utc
from core.db import db_df
from core.i18n import tr
from core.style import hero


def page_users(user: dict) -> None:
    if not has_permission(user, "manage_users"):
        st.error(tr("You do not have permission to manage users.", "У вас нет прав для управления пользователями."))
        return

    hero("Users", tr("Admin area for creating, editing, and deleting users.", "Админка для создания, изменения и удаления пользователей."), ["Admin", "Roles", "Passwords"])
    df = db_df("SELECT username, role, is_active, created_at FROM users ORDER BY username")
    st.dataframe(df, use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader(tr("Create User", "Создать пользователя"))
        with st.form("create_user"):
            username = st.text_input(tr("New username", "Логин нового пользователя"))
            password = st.text_input(tr("Password", "Пароль"), type="password")
            role = st.selectbox(tr("Role", "Роль"), ROLES, format_func=lambda value: ROLE_LABELS[value])
            submitted = st.form_submit_button(tr("Create", "Создать"), use_container_width=True)
        if submitted:
            if not username.strip() or len(password) < 8:
                st.error(tr("Enter a username and a password of at least 8 characters.", "Укажите логин и пароль минимум 8 символов."))
            elif role not in ROLES:
                st.error(tr("Select a valid role.", "Выберите корректную роль."))
            else:
                try:
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute(
                            "INSERT INTO users(username,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?)",
                            (username.strip(), hash_password(password), role, 1, now_utc()),
                        )
                        conn.commit()
                    st.success(tr("User created.", "Пользователь создан."))
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error(tr("This user already exists.", "Такой пользователь уже есть."))
    with c2:
        st.subheader(tr("Edit User", "Редактировать пользователя"))
        users = db_df("SELECT username FROM users ORDER BY username")["username"].tolist()
        with st.form("edit_user"):
            target = st.selectbox(tr("User", "Пользователь"), users)
            current = get_user(target) if target else None
            current_role = current["role"] if current else ROLE_VIEWER
            current_active = bool(current["is_active"]) if current else True
            role = st.selectbox(
                tr("Role", "Роль"),
                ROLES,
                index=ROLES.index(current_role) if current_role in ROLES else 0,
                format_func=lambda value: ROLE_LABELS[value],
            )
            is_active = st.checkbox(tr("Active", "Активен"), value=current_active)
            ok = st.form_submit_button(tr("Save", "Сохранить"), use_container_width=True)
        if ok:
            if target == user["username"] and (role != user["role"] or not is_active):
                st.error(tr("You cannot change your own role or deactivate your own account.", "Нельзя изменить собственную роль или отключить собственную учетную запись."))
            else:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("UPDATE users SET role=?, is_active=? WHERE username=?", (role, int(is_active), target))
                    conn.commit()
                st.success(tr("User updated.", "Пользователь обновлен."))
                st.rerun()
    with c3:
        st.subheader(tr("Password And Deletion", "Пароль и удаление"))
        users = db_df("SELECT username FROM users ORDER BY username")["username"].tolist()
        with st.form("reset_password"):
            target = st.selectbox(tr("User", "Пользователь"), users, key="password_target")
            new_pass = st.text_input(tr("New password", "Новый пароль"), type="password")
            ok = st.form_submit_button(tr("Update password", "Обновить пароль"), use_container_width=True)
        if ok:
            if len(new_pass) < 8:
                st.error(tr("Password must be at least 8 characters.", "Пароль должен быть минимум 8 символов."))
            else:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("UPDATE users SET password_hash=? WHERE username=?", (hash_password(new_pass), target))
                    conn.commit()
                st.success(tr("Password updated.", "Пароль обновлен."))

        with st.form("delete_user"):
            target = st.selectbox(tr("User", "Пользователь"), users, key="delete_target")
            confirm = st.checkbox(tr("I confirm user deletion", "Подтверждаю удаление пользователя"))
            delete_ok = st.form_submit_button(tr("Delete user", "Удалить пользователя"), use_container_width=True)
        if delete_ok:
            if target == user["username"]:
                st.error(tr("You cannot delete your own account.", "Нельзя удалить собственную учетную запись."))
            elif not confirm:
                st.error(tr("Confirm deletion.", "Подтвердите удаление."))
            else:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("DELETE FROM users WHERE username=?", (target,))
                    conn.commit()
                st.success(tr("User deleted.", "Пользователь удален."))
                st.rerun()
