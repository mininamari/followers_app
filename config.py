from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

APP_TITLE = "Instagram followers calculator"
DB_PATH = Path(os.getenv("FOLLOWERS_DB_PATH", "data/followers_team.db"))
UPLOAD_DIR = Path(os.getenv("FOLLOWERS_UPLOAD_DIR", "data/uploads"))
BACKUP_DIR = Path(os.getenv("FOLLOWERS_BACKUP_DIR", "backups"))
BACKUP_RETENTION = int(os.getenv("FOLLOWERS_BACKUP_RETENTION", "8"))
BACKUP_INTERVAL_DAYS = int(os.getenv("FOLLOWERS_BACKUP_INTERVAL_DAYS", "7"))

ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_VIEWER = "viewer"
ROLES = [ROLE_ADMIN, ROLE_MANAGER, ROLE_VIEWER]
ROLE_LABELS = {
    ROLE_ADMIN: "Admin",
    ROLE_MANAGER: "Manager",
    ROLE_VIEWER: "Viewer",
}
PERMISSIONS = {
    ROLE_ADMIN: {
        "view_dashboard", "view_reports", "export_reports", "upload_meta", "upload_pr",
        "edit_reports", "view_history", "manage_users", "manage_backups",
        "view_fb_ads", "manage_fb_ads",
    },
    ROLE_MANAGER: {
        "view_dashboard", "view_reports", "export_reports", "upload_meta", "upload_pr",
        "edit_reports", "view_history",
        "view_fb_ads", "manage_fb_ads",
    },
    ROLE_VIEWER: {"view_dashboard", "view_reports", "export_reports", "view_history", "view_fb_ads"},
}

META_ID_COL = "ID публикации"
META_FOLLOWERS_COL = "Подписки"
META_LINK_COL = "Постоянная ссылка"
META_REACH_COL = "Охват"
META_ACCOUNT_USERNAME_COL = "Имя пользователя аккаунта"
META_ACCOUNT_NAME_COL = "Название аккаунта"
META_PUBLISHED_AT_COL = "Время публикации"
META_COLUMN_ALIASES = {
    META_ID_COL: ["Post ID"],
    META_FOLLOWERS_COL: ["Follows"],
    META_LINK_COL: ["Permalink"],
    META_REACH_COL: ["Reach"],
    META_ACCOUNT_USERNAME_COL: ["Account username"],
    META_ACCOUNT_NAME_COL: ["Account name"],
    META_PUBLISHED_AT_COL: ["Publish time"],
}

PR_START_COL = "Дата начала отчетности"
PR_END_COL = "Окончание отчетности"
PR_AD_NAME_COL = "Название объявления"
PR_FOLLOWERS_COL = "Подписки в Instagram"
PR_SPEND_COL = "Потраченная сумма (USD)"
PR_COLUMN_ALIASES = {
    PR_FOLLOWERS_COL: [
        "Подписчики Instagram",
        "подписчики Instagram",
        "Подписчики IG",
        "подписчики IG",
        "Подписки IG",
        "подписки IG",
    ],
}

REQUIRED_META = [META_ID_COL, META_FOLLOWERS_COL, META_LINK_COL, META_ACCOUNT_USERNAME_COL, META_PUBLISHED_AT_COL]
REQUIRED_PR = [PR_START_COL, PR_END_COL, PR_AD_NAME_COL, PR_FOLLOWERS_COL, PR_SPEND_COL]
MONTH_NAMES = {
    "01": "January",
    "02": "February",
    "03": "March",
    "04": "April",
    "05": "May",
    "06": "June",
    "07": "July",
    "08": "August",
    "09": "September",
    "10": "October",
    "11": "November",
    "12": "December",
}


def now_utc() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except ValueError:
        return None
