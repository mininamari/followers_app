from __future__ import annotations

import pandas as pd
import streamlit as st

from core.auth import has_permission
from core.config import BACKUP_DIR, BACKUP_RETENTION
from core.db import create_manual_backup, get_setting, list_backups
from core.i18n import tr
from core.style import hero


def page_backups(user: dict) -> None:
    if not has_permission(user, "manage_backups"):
        st.error(tr("You do not have permission to manage backups.", "У вас нет прав для управления резервными копиями."))
        return

    hero(
        "Backups",
        tr(
            "SQLite backups are created automatically once a week. Admins can create and download a backup manually.",
            "Резервные копии SQLite создаются автоматически раз в неделю. Администратор может создать и скачать копию вручную.",
        ),
        ["Weekly", f"Keep last {BACKUP_RETENTION}", "SQLite snapshot"],
    )
    last_backup = get_setting("last_weekly_backup_at")
    st.caption(f"{tr('Backup directory', 'Папка резервных копий')}: {BACKUP_DIR}")
    st.caption(f"{tr('Last scheduled/manual backup', 'Последняя автоматическая/ручная копия')}: {last_backup or tr('never', 'никогда')}")

    if st.button(tr("Create Backup", "Создать резервную копию"), type="primary", use_container_width=True):
        try:
            backup_path = create_manual_backup(user)
            st.success(tr(f"Backup created: {backup_path.name}", f"Резервная копия создана: {backup_path.name}"))
            st.rerun()
        except Exception as exc:
            st.error(tr(f"Backup failed: {exc}", f"Ошибка резервного копирования: {exc}"))

    backups = list_backups()
    if not backups:
        st.info(tr("No backups yet.", "Резервных копий пока нет."))
        return

    table = pd.DataFrame(
        [
            {
                "file": backup["name"],
                "created_at": backup["created_at"],
                "size_mb": round(backup["size_bytes"] / 1024 / 1024, 2),
            }
            for backup in backups
        ]
    )
    st.dataframe(table, use_container_width=True, hide_index=True)

    st.markdown("### " + tr("Download Backup", "Скачать резервную копию"))
    selected_name = st.selectbox(tr("Backup file", "Файл резервной копии"), [backup["name"] for backup in backups])
    selected = next(backup for backup in backups if backup["name"] == selected_name)
    st.download_button(
        tr("Download Backup", "Скачать резервную копию"),
        data=selected["path"].read_bytes(),
        file_name=selected["name"],
        mime="application/octet-stream",
        use_container_width=True,
    )
