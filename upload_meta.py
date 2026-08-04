from __future__ import annotations

import streamlit as st

from core.auth import has_permission
from core.csv_import import import_meta, infer_accounts_from_meta, read_csv_any
from core.i18n import tr
from core.style import hero


def page_upload_meta(user: dict) -> None:
    if not has_permission(user, "upload_meta"):
        st.error(tr("You do not have permission to upload Meta CSV files.", "У вас нет прав для загрузки Meta CSV."))
        return
    hero(
        "Upload Meta",
        tr(
            "Upload a CSV from Meta Business Suite. Russian and English exports are mapped to accounts by username.",
            "Загрузите CSV из Meta Business Suite. Русские и английские выгрузки распределяются по аккаунтам через username.",
        ),
        ["RU/EN columns", "Combined exports", "1+ followers only", "Post links"],
    )
    meta_file = st.file_uploader(tr("Meta Business Suite CSV", "CSV из Meta Business Suite"), type=["csv"], key="meta")
    c1, c2 = st.columns(2)
    manual_start = c1.date_input(tr("Period start if it cannot be detected from the filename", "Начало периода, если не определяется из имени файла"), value=None)
    manual_end = c2.date_input(tr("Period end if it cannot be detected from the filename", "Конец периода, если не определяется из имени файла"), value=None)
    if meta_file:
        try:
            preview = read_csv_any(meta_file)
            accs = infer_accounts_from_meta(preview)
            st.success(tr("Detected accounts: ", "Найденные аккаунты: ") + (", ".join(accs) if accs else tr("could not detect", "не удалось определить")))
            st.dataframe(preview.head(10), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(str(exc))
    if st.button(tr("Save Meta and recalculate", "Сохранить Meta и пересчитать"), type="primary", use_container_width=True):
        if not meta_file:
            st.error(tr("Upload a CSV file.", "Загрузите CSV."))
        else:
            try:
                rows, warnings = import_meta(meta_file, user, manual_start, manual_end)
                st.success(tr(f"Meta saved. Rows: {rows}. The report was recalculated automatically.", f"Meta сохранена. Строк: {rows}. Отчет пересчитан автоматически."))
                for w in warnings:
                    st.warning(w)
            except Exception as exc:
                st.error(str(exc))
