from __future__ import annotations

import streamlit as st

from core.auth import has_permission
from core.csv_import import import_pr, read_csv_any
from core.db import accounts_in_db
from core.i18n import tr
from core.style import hero


def page_upload_pr(user: dict) -> None:
    if not has_permission(user, "upload_pr"):
        st.error(tr("You do not have permission to upload PR CSV files.", "У вас нет прав для загрузки PR CSV."))
        return
    hero(
        "Upload PR",
        tr(
            "Upload a CSV from the ad account. The app can distribute a shared PR file by matching publication IDs from Meta.",
            "Таргетолог загружает CSV из рекламного кабинета. Система распределит общий PR-файл по аккаунтам через ID публикации из Meta.",
        ),
        ["Auto account distribution", "Spend", "CPF", "Auto recalc"],
    )
    auto_detect = st.checkbox(tr("Automatically distribute by Meta publication ID", "Автоматически распределить по аккаунтам через ID публикации из Meta"), value=True)
    existing = accounts_in_db()
    default_options = existing + ["novakid_israel", "novakid_france", "novakid_spain", "novakid_turkey"]
    default_options = sorted(set(default_options))
    account = ""
    if not auto_detect:
        selected = st.selectbox(tr("Region / account", "Регион / аккаунт"), default_options, index=0 if default_options else None)
        custom = st.text_input(tr("Or enter a new account manually", "Или введите новый аккаунт вручную"), placeholder="novakid_germany")
        account = custom.strip() or selected
    pr_file = st.file_uploader(tr("Novakid PR CSV", "CSV из Novakid PR"), type=["csv"], key="pr")
    if pr_file:
        try:
            preview = read_csv_any(pr_file)
            st.dataframe(preview.head(10), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(str(exc))
    if st.button(tr("Save PR and recalculate", "Сохранить PR и пересчитать"), type="primary", use_container_width=True):
        if not pr_file:
            st.error(tr("Upload a CSV file.", "Загрузите CSV."))
        else:
            try:
                rows, warnings = import_pr(pr_file, user, account, auto_detect)
                target = tr("by Meta accounts", "по аккаунтам из Meta") if auto_detect else tr(f"for {account}", f"для {account}")
                st.success(tr(f"PR saved {target}. Rows: {rows}. The report was recalculated automatically.", f"PR сохранен {target}. Строк: {rows}. Отчет пересчитан автоматически."))
                for w in warnings:
                    st.warning(w)
            except Exception as exc:
                st.error(str(exc))
