from __future__ import annotations

import streamlit as st

from core.auth import has_permission
from core.db import db_df
from core.i18n import tr
from core.style import hero


def page_upload_history() -> None:
    user = st.session_state.get("user")
    if not has_permission(user, "view_history"):
        st.error(tr("You do not have permission to view upload history.", "У вас нет прав для просмотра истории загрузок."))
        return
    hero("Upload history", tr("Who uploaded which files and when. This helps verify report freshness.", "Кто, когда и какие файлы загружал. Это помогает проверять актуальность отчетов."), ["Audit", "Files", "Rows saved"])
    df = db_df("SELECT file_type, account, period_start, period_end, filename, uploaded_by, uploaded_at, rows_saved, warnings FROM uploads ORDER BY uploaded_at DESC")
    if df.empty:
        st.info(tr("No uploads yet.", "Загрузок пока нет."))
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)
