from __future__ import annotations

import base64
import hashlib
import hmac
import io
import os
import re
import secrets
import sqlite3
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional, Iterable

import pandas as pd
import plotly.express as px
import streamlit as st

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
    },
    ROLE_MANAGER: {
        "view_dashboard", "view_reports", "export_reports", "upload_meta", "upload_pr",
        "edit_reports", "view_history",
    },
    ROLE_VIEWER: {"view_dashboard", "view_reports", "export_reports", "view_history"},
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


# -------------------- DB + auth --------------------

def now_utc() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except ValueError:
        return None


def has_permission(user: Optional[dict], permission: str) -> bool:
    if not user:
        return False
    return permission in PERMISSIONS.get(user.get("role", ""), set())


def require_permission(user: Optional[dict], permission: str) -> None:
    if not has_permission(user, permission):
        raise PermissionError("У вас нет прав для этого действия.")


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin','manager','viewer')),
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        migrate_user_roles(conn)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS uploads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_type TEXT NOT NULL CHECK(file_type IN ('meta','pr')),
                account TEXT,
                period_start TEXT,
                period_end TEXT,
                filename TEXT NOT NULL,
                stored_path TEXT,
                uploaded_by TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                rows_saved INTEGER NOT NULL DEFAULT 0,
                warnings TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS meta_publications (
                account TEXT NOT NULL,
                account_name TEXT,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                month TEXT NOT NULL,
                publication_date TEXT,
                publication_id TEXT NOT NULL,
                publication_link TEXT,
                post_reach INTEGER NOT NULL DEFAULT 0,
                meta_followers INTEGER NOT NULL DEFAULT 0,
                meta_filename TEXT,
                uploaded_by TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                PRIMARY KEY(account, period_start, period_end, publication_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pr_ads (
                account TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                month TEXT NOT NULL,
                publication_id TEXT NOT NULL,
                pr_followers INTEGER NOT NULL DEFAULT 0,
                spend_usd REAL NOT NULL DEFAULT 0,
                pr_filename TEXT,
                uploaded_by TEXT NOT NULL,
                uploaded_at TEXT NOT NULL,
                PRIMARY KEY(account, period_start, period_end, publication_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS final_results (
                account TEXT NOT NULL,
                account_name TEXT,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                month TEXT NOT NULL,
                publication_date TEXT,
                publication_id TEXT NOT NULL,
                publication_link TEXT,
                post_reach INTEGER NOT NULL DEFAULT 0,
                meta_followers INTEGER NOT NULL DEFAULT 0,
                pr_followers INTEGER NOT NULL DEFAULT 0,
                final_followers INTEGER NOT NULL DEFAULT 0,
                spend_usd REAL NOT NULL DEFAULT 0,
                cpf_usd REAL,
                warning TEXT,
                meta_uploaded_by TEXT,
                pr_uploaded_by TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(account, period_start, period_end, publication_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS follower_overrides (
                account TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                publication_id TEXT NOT NULL,
                manual_pr_followers INTEGER NOT NULL CHECK(manual_pr_followers >= 0),
                updated_by TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(account, period_start, period_end, publication_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.commit()
        ensure_schema_columns(conn)
        purge_non_novakid_data(conn)
        sanitize_stored_meta_uploads(conn)
        backfill_stored_meta_reach(conn)
        ensure_default_admin(conn)
    maybe_create_weekly_backup()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return "pbkdf2_sha256$200000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, hash_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(got, expected)
    except Exception:
        return False


def ensure_default_admin(conn: sqlite3.Connection) -> None:
    cur = conn.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        username = os.getenv("FOLLOWERS_ADMIN_USERNAME", "").strip()
        password = os.getenv("FOLLOWERS_ADMIN_PASSWORD", "")
        if not username or not password:
            return
        if len(password) < 8:
            raise ValueError("FOLLOWERS_ADMIN_PASSWORD must be at least 8 characters long.")
        conn.execute(
            "INSERT INTO users(username,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?)",
            (username, hash_password(password), ROLE_ADMIN, 1, now_utc()),
        )
        conn.commit()


def migrate_user_roles(conn: sqlite3.Connection) -> None:
    table_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    if not table_sql:
        return

    sql = table_sql[0] or ""
    needs_rebuild = "'user'" in sql or '"user"' in sql
    roles = {row[0] for row in conn.execute("SELECT DISTINCT role FROM users")}
    if not needs_rebuild and roles.issubset(set(ROLES)):
        return

    conn.execute("ALTER TABLE users RENAME TO users_legacy")
    conn.execute(
        """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','manager','viewer')),
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
        """
    )
    legacy_rows = conn.execute(
        "SELECT id, username, password_hash, role, is_active, created_at FROM users_legacy"
    ).fetchall()
    for user_id, username, password_hash, role, is_active, created_at in legacy_rows:
        migrated_role = ROLE_ADMIN if role == "admin" else ROLE_MANAGER
        conn.execute(
            """
            INSERT INTO users(id, username, password_hash, role, is_active, created_at)
            VALUES(?,?,?,?,?,?)
            """,
            (user_id, username, password_hash, migrated_role, is_active, created_at),
        )
    conn.execute("DROP TABLE users_legacy")
    conn.commit()


def ensure_schema_columns(conn: sqlite3.Connection) -> None:
    for table in ("meta_publications", "final_results"):
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        if "publication_date" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN publication_date TEXT")
        if "post_reach" not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN post_reach INTEGER NOT NULL DEFAULT 0")
    final_cols = {row[1] for row in conn.execute("PRAGMA table_info(final_results)")}
    additions = {
        "imported_pr_followers": "INTEGER NOT NULL DEFAULT 0",
        "manual_pr_followers": "INTEGER",
        "override_updated_by": "TEXT",
        "override_updated_at": "TEXT",
    }
    for column, definition in additions.items():
        if column not in final_cols:
            conn.execute(f"ALTER TABLE final_results ADD COLUMN {column} {definition}")
            if column == "imported_pr_followers":
                conn.execute("UPDATE final_results SET imported_pr_followers=pr_followers")
    conn.commit()


def is_novakid_account(account: object) -> bool:
    return str(account).strip().lstrip("@").lower().startswith("novakid")


def purge_non_novakid_data(conn: sqlite3.Connection) -> None:
    for table in ("follower_overrides", "final_results", "pr_ads", "meta_publications"):
        conn.execute(
            f"DELETE FROM {table} WHERE lower(ltrim(account, '@')) NOT LIKE 'novakid%'"
        )
    conn.execute(
        """
        DELETE FROM uploads
        WHERE account IS NOT NULL
          AND account != 'auto'
          AND lower(ltrim(account, '@')) NOT LIKE 'novakid%'
        """
    )
    conn.commit()


def sanitize_stored_meta_uploads(conn: sqlite3.Connection) -> None:
    stored_files = conn.execute(
        "SELECT id, stored_path FROM uploads WHERE file_type='meta' AND stored_path IS NOT NULL"
    ).fetchall()
    for _, stored_path in stored_files:
        path = Path(stored_path)
        if not path.exists():
            continue
        try:
            uploaded_file = io.BytesIO(path.read_bytes())
            df, _ = normalize_meta_columns(read_csv_any(uploaded_file))
            if META_ACCOUNT_USERNAME_COL not in df.columns:
                continue
            keep = df[META_ACCOUNT_USERNAME_COL].apply(is_novakid_account)
            if keep.all():
                continue
            filtered = df[keep].copy()
            path.write_bytes(filtered.to_csv(index=False).encode("utf-8-sig"))
        except Exception:
            continue
    conn.commit()


def backfill_stored_meta_reach(conn: sqlite3.Connection) -> None:
    stored_files = conn.execute(
        """
        SELECT period_start, period_end, stored_path
        FROM uploads
        WHERE file_type='meta' AND stored_path IS NOT NULL
        ORDER BY uploaded_at
        """
    ).fetchall()
    for period_start, period_end, stored_path in stored_files:
        path = Path(stored_path)
        if not path.exists():
            continue
        try:
            uploaded_file = io.BytesIO(path.read_bytes())
            df, _ = normalize_meta_columns(read_csv_any(uploaded_file))
            if META_REACH_COL not in df.columns:
                continue
            df[META_ID_COL] = df[META_ID_COL].apply(clean_id)
            df[META_ACCOUNT_USERNAME_COL] = df[META_ACCOUNT_USERNAME_COL].astype(str).str.strip()
            df[META_REACH_COL] = to_number(df[META_REACH_COL]).astype(int)
            grouped = (
                df[df[META_ACCOUNT_USERNAME_COL].apply(is_novakid_account)]
                .groupby([META_ACCOUNT_USERNAME_COL, META_ID_COL], as_index=False)[META_REACH_COL]
                .max()
            )
            conn.executemany(
                """
                UPDATE meta_publications
                SET post_reach=?
                WHERE account=? AND period_start=? AND period_end=? AND publication_id=?
                """,
                [
                    (
                        int(row[META_REACH_COL]), str(row[META_ACCOUNT_USERNAME_COL]),
                        period_start, period_end, str(row[META_ID_COL]),
                    )
                    for _, row in grouped.iterrows()
                ],
            )
        except Exception:
            continue
    conn.execute(
        """
        UPDATE final_results
        SET post_reach=COALESCE((
            SELECT meta_publications.post_reach
            FROM meta_publications
            WHERE meta_publications.account=final_results.account
              AND meta_publications.period_start=final_results.period_start
              AND meta_publications.period_end=final_results.period_end
              AND meta_publications.publication_id=final_results.publication_id
        ), 0)
        """
    )
    conn.commit()


def get_user(username: str) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None


def authenticate(username: str, password: str) -> Optional[dict]:
    user = get_user(username.strip())
    if user and user["is_active"] and verify_password(password, user["password_hash"]):
        return user
    return None


def get_setting(key: str) -> Optional[str]:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute("SELECT value FROM system_settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else None


def set_setting(key: str, value: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO system_settings(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (key, value),
        )
        conn.commit()


def list_backups() -> list[dict]:
    if not BACKUP_DIR.exists():
        return []
    backups = []
    for path in sorted(BACKUP_DIR.glob("followers_team_*.db"), reverse=True):
        if not path.is_file():
            continue
        stat = path.stat()
        backups.append(
            {
                "name": path.name,
                "path": path,
                "created_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(timespec="seconds") + "Z",
                "size_bytes": stat.st_size,
            }
        )
    return backups


def prune_old_backups() -> None:
    backups = list_backups()
    for backup in backups[BACKUP_RETENTION:]:
        try:
            backup["path"].unlink()
        except OSError:
            continue


def create_backup(created_by: str = "system") -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    target = BACKUP_DIR / f"followers_team_{timestamp}.db"
    temp_target = target.with_suffix(".tmp")

    with sqlite3.connect(DB_PATH) as source, sqlite3.connect(temp_target) as destination:
        source.backup(destination, pages=100, sleep=0.05)
    temp_target.replace(target)
    prune_old_backups()
    set_setting("last_weekly_backup_at", now_utc())
    set_setting("last_backup_created_by", created_by)
    return target


def create_manual_backup(user: dict) -> Path:
    require_permission(user, "manage_backups")
    return create_backup(user["username"])


def maybe_create_weekly_backup() -> None:
    last_backup_at = parse_utc(get_setting("last_weekly_backup_at"))
    if last_backup_at and datetime.utcnow() - last_backup_at < timedelta(days=BACKUP_INTERVAL_DAYS):
        return
    try:
        create_backup("system")
    except Exception:
        # Backup failures should not prevent users from opening the app.
        return


# -------------------- CSV helpers --------------------

def read_csv_any(uploaded_file) -> pd.DataFrame:
    raw = uploaded_file.getvalue()
    for enc in ("utf-8-sig", "utf-16", "cp1251", "latin1"):
        try:
            text = raw.decode(enc)
            first = text.splitlines()[0]
            sep = ";" if first.count(";") > first.count(",") else ","
            return pd.read_csv(io.StringIO(text), sep=sep)
        except Exception:
            continue
    raise ValueError("Не удалось прочитать CSV. Проверьте кодировку и формат файла.")


def save_uploaded_file(uploaded_file, file_type: str, data: Optional[bytes] = None) -> str:
    safe_name = re.sub(r"[^A-Za-zА-Яа-я0-9_.() -]+", "_", uploaded_file.name)
    target = UPLOAD_DIR / file_type / datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    target.mkdir(parents=True, exist_ok=True)
    path = target / safe_name
    with path.open("wb") as f:
        f.write(uploaded_file.getvalue() if data is None else data)
    return str(path)


def clean_id(value) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if re.fullmatch(r"\d+\.0", text):
        text = text[:-2]
    return text


def to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(" ", "", regex=False).str.replace(",", ".", regex=False),
        errors="coerce",
    ).fillna(0)


def normalize_period(value) -> str:
    dt = pd.to_datetime(value, errors="coerce", dayfirst=False)
    if pd.isna(dt):
        dt = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(dt):
        raise ValueError(f"Не удалось распознать дату периода: {value}")
    return dt.date().isoformat()


def normalize_publication_date(value) -> str:
    dt = pd.to_datetime(value, errors="coerce", dayfirst=False)
    if pd.isna(dt):
        dt = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(dt):
        raise ValueError(f"Не удалось распознать дату публикации: {value}")
    return dt.date().isoformat()


def month_from_period(period_start: str) -> str:
    return period_start[:7]


def validate_columns(df: pd.DataFrame, required: list[str], file_label: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"В файле {file_label} нет колонок: {', '.join(missing)}")


def normalize_meta_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    rename_map = {}
    used_aliases = []
    for canonical, aliases in META_COLUMN_ALIASES.items():
        if canonical in df.columns:
            continue
        for alias in aliases:
            if alias in df.columns:
                rename_map[alias] = canonical
                used_aliases.append(f"{alias} -> {canonical}")
                break

    normalized = df.rename(columns=rename_map).copy()
    return normalized, used_aliases


def parse_meta_period_from_filename(filename: str) -> Optional[tuple[str, str]]:
    month_map = {
        "jan": "01", "feb": "02", "mar": "03", "apr": "04", "may": "05", "jun": "06",
        "jul": "07", "aug": "08", "sep": "09", "oct": "10", "nov": "11", "dec": "12",
    }
    pattern = re.compile(
        r"(?P<m1>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(?P<d1>\d{1,2})-(?P<y1>\d{4})"
        r"[_\s-]+"
        r"(?P<m2>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-(?P<d2>\d{1,2})-(?P<y2>\d{4})",
        re.IGNORECASE,
    )
    m = pattern.search(filename)
    if not m:
        return None
    start = f"{m.group('y1')}-{month_map[m.group('m1').lower()]}-{int(m.group('d1')):02d}"
    end = f"{m.group('y2')}-{month_map[m.group('m2').lower()]}-{int(m.group('d2')):02d}"
    return start, end


def infer_accounts_from_meta(df: pd.DataFrame) -> list[str]:
    df, _ = normalize_meta_columns(df)
    if META_ACCOUNT_USERNAME_COL not in df.columns:
        return []
    return sorted([
        str(x).strip()
        for x in df[META_ACCOUNT_USERNAME_COL].dropna().unique()
        if is_novakid_account(x)
    ])


def db_df(query: str, params: Iterable = ()) -> pd.DataFrame:
    with sqlite3.connect(DB_PATH) as conn:
        return pd.read_sql_query(query, conn, params=tuple(params))


def accounts_in_db() -> list[str]:
    df = db_df(
        """
        SELECT account FROM meta_publications
        UNION
        SELECT account FROM pr_ads
        ORDER BY account
        """
    )
    return df["account"].tolist() if not df.empty else []


def monthly_increment_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["month", "account", "monthly_followers", "month_label"])

    monthly = (
        df.groupby(["month", "account"], as_index=False)["final_followers"]
        .sum()
        .sort_values(["account", "month"])
    )
    monthly["monthly_followers"] = monthly["final_followers"].astype(int)
    monthly["month_label"] = pd.to_datetime(monthly["month"] + "-01").dt.strftime("%b %Y")
    return monthly


def latest_publications_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    sort_cols = [c for c in ["account", "publication_id", "month", "period_end", "updated_at"] if c in df.columns]
    latest = df.sort_values(sort_cols).drop_duplicates(["account", "publication_id", "month"], keep="last")
    return latest


# -------------------- Recalculation --------------------

def recalc_final(account: str, period_start: str, period_end: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        meta_rows = conn.execute(
            "SELECT * FROM meta_publications WHERE account=? AND period_start=? AND period_end=?",
            (account, period_start, period_end),
        ).fetchall()
        current = now_utc()
        conn.execute(
            "DELETE FROM final_results WHERE account=? AND period_start=? AND period_end=?",
            (account, period_start, period_end),
        )
        for m in meta_rows:
            pr = conn.execute(
                "SELECT * FROM pr_ads WHERE account=? AND period_start=? AND period_end=? AND publication_id=?",
                (account, period_start, period_end, m["publication_id"]),
            ).fetchone()
            imported_pr_followers = int(pr["pr_followers"]) if pr else 0
            override = conn.execute(
                """
                SELECT manual_pr_followers, updated_by, updated_at
                FROM follower_overrides
                WHERE account=? AND period_start=? AND period_end=? AND publication_id=?
                """,
                (account, period_start, period_end, m["publication_id"]),
            ).fetchone()
            manual_pr_followers = int(override["manual_pr_followers"]) if override else None
            pr_followers = manual_pr_followers if manual_pr_followers is not None else imported_pr_followers
            spend = float(pr["spend_usd"]) if pr else 0.0
            raw_final = int(m["meta_followers"]) - pr_followers
            warning = ""
            if raw_final < 0:
                warning = "Получилось отрицательное значение подписчиков. Нужно проверить Meta/Novakid PR."
            final_followers = max(0, raw_final)
            cpf = round(spend / pr_followers, 4) if pr_followers > 0 else None
            conn.execute(
                """
                INSERT INTO final_results(
                    account, account_name, period_start, period_end, month, publication_date, publication_id, publication_link,
                    post_reach, meta_followers, imported_pr_followers, manual_pr_followers, pr_followers, final_followers,
                    spend_usd, cpf_usd, warning, meta_uploaded_by, pr_uploaded_by,
                    override_updated_by, override_updated_at, updated_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    account, m["account_name"], period_start, period_end, m["month"], m["publication_date"], m["publication_id"],
                    m["publication_link"], int(m["post_reach"]), int(m["meta_followers"]), imported_pr_followers, manual_pr_followers,
                    pr_followers, final_followers, spend, cpf, warning, m["uploaded_by"],
                    pr["uploaded_by"] if pr else None, override["updated_by"] if override else None,
                    override["updated_at"] if override else None, current,
                ),
            )
        conn.commit()


def save_follower_overrides(rows: pd.DataFrame, user: dict) -> int:
    require_permission(user, "edit_reports")
    selected = rows[rows["Изменить"] == True].copy()  # noqa: E712
    if selected.empty:
        raise ValueError("Отметьте строки, для которых нужно сохранить ручное значение.")

    affected_periods: set[tuple[str, str, str]] = set()
    updated_at = now_utc()
    with sqlite3.connect(DB_PATH) as conn:
        for _, row in selected.iterrows():
            key = (str(row["account"]), str(row["period_start"]), str(row["period_end"]), str(row["publication_id"]))
            value = row["manual_pr_followers"]
            if pd.isna(value):
                conn.execute(
                    """
                    DELETE FROM follower_overrides
                    WHERE account=? AND period_start=? AND period_end=? AND publication_id=?
                    """,
                    key,
                )
            else:
                manual_value = int(value)
                if manual_value < 0:
                    raise ValueError("Ручное количество подписчиков не может быть отрицательным.")
                conn.execute(
                    """
                    INSERT INTO follower_overrides(
                        account, period_start, period_end, publication_id,
                        manual_pr_followers, updated_by, updated_at
                    ) VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(account, period_start, period_end, publication_id)
                    DO UPDATE SET
                        manual_pr_followers=excluded.manual_pr_followers,
                        updated_by=excluded.updated_by,
                        updated_at=excluded.updated_at
                    """,
                    (*key, manual_value, user["username"], updated_at),
                )
            affected_periods.add(key[:3])
        conn.commit()

    for account, period_start, period_end in affected_periods:
        recalc_final(account, period_start, period_end)
    return len(selected)


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Report")
    return output.getvalue()


# -------------------- Import logic --------------------

def import_meta(uploaded_file, user: dict, manual_start: Optional[date], manual_end: Optional[date]) -> tuple[int, list[str]]:
    require_permission(user, "upload_meta")
    df = read_csv_any(uploaded_file)
    df, used_aliases = normalize_meta_columns(df)
    validate_columns(df, REQUIRED_META, "Meta Business Suite")
    period = parse_meta_period_from_filename(uploaded_file.name)
    warnings: list[str] = []
    if used_aliases:
        warnings.append("Meta-колонки распознаны по английским названиям: " + ", ".join(used_aliases) + ".")
    if period:
        period_start, period_end = period
    elif manual_start and manual_end:
        period_start, period_end = manual_start.isoformat(), manual_end.isoformat()
        warnings.append("Период Meta взят из ручного ввода, потому что его не удалось определить из имени файла.")
    else:
        raise ValueError("Не удалось определить период Meta из имени файла. Укажите даты вручную.")

    if period_start > period_end:
        raise ValueError("Дата начала периода больше даты окончания.")

    df = df.copy()
    df[META_ID_COL] = df[META_ID_COL].apply(clean_id)
    df[META_PUBLISHED_AT_COL] = df[META_PUBLISHED_AT_COL].apply(normalize_publication_date)
    df[META_FOLLOWERS_COL] = to_number(df[META_FOLLOWERS_COL]).astype(int)
    if META_REACH_COL not in df.columns:
        df[META_REACH_COL] = 0
        warnings.append("В Meta-файле нет колонки охвата; для публикаций сохранено значение 0.")
    df[META_REACH_COL] = to_number(df[META_REACH_COL]).astype(int)
    df[META_ACCOUNT_USERNAME_COL] = df[META_ACCOUNT_USERNAME_COL].astype(str).str.strip()
    if META_ACCOUNT_NAME_COL not in df.columns:
        df[META_ACCOUNT_NAME_COL] = ""

    df = df[(df[META_ID_COL] != "") & (df[META_ACCOUNT_USERNAME_COL] != "") & (df[META_FOLLOWERS_COL] >= 1)].copy()
    skipped_accounts = sorted(
        df.loc[~df[META_ACCOUNT_USERNAME_COL].apply(is_novakid_account), META_ACCOUNT_USERNAME_COL].unique().tolist()
    )
    df = df[df[META_ACCOUNT_USERNAME_COL].apply(is_novakid_account)].copy()
    if skipped_accounts:
        warnings.append(
            f"Пропущены аккаунты блогеров ({len(skipped_accounts)}): {', '.join(skipped_accounts[:10])}"
            + (" и другие." if len(skipped_accounts) > 10 else ".")
        )
    if df.empty:
        raise ValueError("В Meta-файле нет публикаций Novakid с 1+ подписчиком.")

    # Внутри файла группируем по аккаунту + ID, чтобы не было дублей.
    grouped = (
        df.groupby([META_ACCOUNT_USERNAME_COL, META_ID_COL], as_index=False)
        .agg({
            META_ACCOUNT_NAME_COL: "first",
            META_LINK_COL: "first",
            META_PUBLISHED_AT_COL: "first",
            META_REACH_COL: "max",
            META_FOLLOWERS_COL: "sum",
        })
    )

    filtered_file = df.to_csv(index=False).encode("utf-8-sig")
    stored_path = save_uploaded_file(uploaded_file, "meta", filtered_file)
    uploaded_at = now_utc()
    rows = []
    for _, r in grouped.iterrows():
        publication_date = r[META_PUBLISHED_AT_COL]
        month = month_from_period(publication_date)
        rows.append((
            r[META_ACCOUNT_USERNAME_COL], r.get(META_ACCOUNT_NAME_COL, ""), period_start, period_end, month, publication_date,
            r[META_ID_COL], r.get(META_LINK_COL, ""), int(r[META_REACH_COL]), int(r[META_FOLLOWERS_COL]), uploaded_file.name,
            user["username"], uploaded_at,
        ))

    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            """
            INSERT INTO meta_publications(
                account, account_name, period_start, period_end, month, publication_date, publication_id, publication_link,
                post_reach, meta_followers, meta_filename, uploaded_by, uploaded_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(account, period_start, period_end, publication_id)
            DO UPDATE SET
                account_name=excluded.account_name,
                month=excluded.month,
                publication_date=excluded.publication_date,
                publication_link=excluded.publication_link,
                post_reach=excluded.post_reach,
                meta_followers=excluded.meta_followers,
                meta_filename=excluded.meta_filename,
                uploaded_by=excluded.uploaded_by,
                uploaded_at=excluded.uploaded_at
            """,
            rows,
        )
        conn.execute(
            "INSERT INTO uploads(file_type,account,period_start,period_end,filename,stored_path,uploaded_by,uploaded_at,rows_saved,warnings) VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("meta", None, period_start, period_end, uploaded_file.name, stored_path, user["username"], uploaded_at, len(rows), "\n".join(warnings)),
        )
        conn.commit()

    for account in sorted(grouped[META_ACCOUNT_USERNAME_COL].unique()):
        recalc_final(str(account), period_start, period_end)
    return len(rows), warnings


def import_pr(uploaded_file, user: dict, account: str, auto_detect_accounts: bool = False) -> tuple[int, list[str]]:
    require_permission(user, "upload_pr")
    if not auto_detect_accounts and not account.strip():
        raise ValueError("Для PR-файла нужно выбрать аккаунт, например novakid_israel.")
    account = account.strip()
    if not auto_detect_accounts and not is_novakid_account(account):
        raise ValueError("Можно сохранять данные только для аккаунтов Novakid.")
    df = read_csv_any(uploaded_file)
    validate_columns(df, REQUIRED_PR, "Novakid PR")
    df = df.copy()
    df[PR_START_COL] = df[PR_START_COL].apply(normalize_period)
    df[PR_END_COL] = df[PR_END_COL].apply(normalize_period)
    starts = sorted(df[PR_START_COL].dropna().unique())
    ends = sorted(df[PR_END_COL].dropna().unique())
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError("В Novakid PR найдено несколько периодов. Загрузите файл только за один период.")
    period_start, period_end = starts[0], ends[0]
    month = month_from_period(period_start)

    df[PR_AD_NAME_COL] = df[PR_AD_NAME_COL].apply(clean_id)
    df[PR_FOLLOWERS_COL] = to_number(df[PR_FOLLOWERS_COL]).astype(int)
    df[PR_SPEND_COL] = to_number(df[PR_SPEND_COL]).astype(float)
    df = df[df[PR_AD_NAME_COL] != ""].copy()
    grouped = (
        df.groupby(PR_AD_NAME_COL, as_index=False)
        .agg({PR_FOLLOWERS_COL: "sum", PR_SPEND_COL: "sum"})
        .rename(columns={PR_AD_NAME_COL: "publication_id"})
    )
    if grouped.empty:
        raise ValueError("В Novakid PR нет строк с заполненным названием объявления.")

    warnings: list[str] = []
    if auto_detect_accounts:
        ids = grouped["publication_id"].dropna().astype(str).tolist()
        placeholders = ",".join(["?"] * len(ids))
        with sqlite3.connect(DB_PATH) as conn:
            meta_matches = pd.read_sql_query(
                f"""
                SELECT publication_id, account
                FROM meta_publications
                WHERE period_start=? AND period_end=? AND publication_id IN ({placeholders})
                GROUP BY publication_id, account
                """,
                conn,
                params=(period_start, period_end, *ids),
            )

        if meta_matches.empty:
            raise ValueError("Не найдено совпадений PR с Meta по ID публикации за этот период.")

        account_counts = meta_matches.groupby("publication_id")["account"].nunique()
        ambiguous_ids = set(account_counts[account_counts > 1].index.astype(str))
        matched_once = meta_matches[~meta_matches["publication_id"].isin(ambiguous_ids)].copy()
        grouped = grouped.merge(matched_once, on="publication_id", how="left")

        unmatched_ids = grouped.loc[grouped["account"].isna(), "publication_id"].astype(str).tolist()
        excluded_ids = sorted(set(unmatched_ids) | ambiguous_ids)
        if excluded_ids:
            preview = ", ".join(excluded_ids[:25])
            extra = "" if len(excluded_ids) <= 25 else f" и еще {len(excluded_ids) - 25}"
            warnings.append(
                f"Исключены строки PR без однозначного совпадения с Meta по ID публикации: {preview}{extra}."
            )

        grouped = grouped[grouped["account"].notna()].copy()
        if grouped.empty:
            raise ValueError("После исключения несовпавших ID не осталось строк PR для сохранения.")
    else:
        grouped["account"] = account

    stored_path = save_uploaded_file(uploaded_file, "pr")
    uploaded_at = now_utc()
    rows = []
    for _, r in grouped.iterrows():
        rows.append((
            r["account"], period_start, period_end, month, r["publication_id"], int(r[PR_FOLLOWERS_COL]),
            float(r[PR_SPEND_COL]), uploaded_file.name, user["username"], uploaded_at,
        ))

    with sqlite3.connect(DB_PATH) as conn:
        conn.executemany(
            """
            INSERT INTO pr_ads(
                account, period_start, period_end, month, publication_id, pr_followers, spend_usd,
                pr_filename, uploaded_by, uploaded_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(account, period_start, period_end, publication_id)
            DO UPDATE SET
                month=excluded.month,
                pr_followers=excluded.pr_followers,
                spend_usd=excluded.spend_usd,
                pr_filename=excluded.pr_filename,
                uploaded_by=excluded.uploaded_by,
                uploaded_at=excluded.uploaded_at
            """,
            rows,
        )
        conn.execute(
            "INSERT INTO uploads(file_type,account,period_start,period_end,filename,stored_path,uploaded_by,uploaded_at,rows_saved,warnings) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "pr",
                "auto" if auto_detect_accounts else account,
                period_start,
                period_end,
                uploaded_file.name,
                stored_path,
                user["username"],
                uploaded_at,
                len(rows),
                "\n".join(warnings),
            ),
        )
        conn.commit()

    for affected_account in sorted(grouped["account"].dropna().astype(str).unique()):
        recalc_final(affected_account, period_start, period_end)
    return len(rows), warnings


# -------------------- UI --------------------

NOVAKID_CSS = """
<style>
:root {
    --nk-purple: #6D3DF5;
    --nk-purple-dark: #4E2AC8;
    --nk-blue: #00A6FF;
    --nk-green: #53D86A;
    --nk-yellow: #FFD84D;
    --nk-pink: #FF6FAE;
    --nk-orange: #FF9F2E;
    --nk-bg: #F7F4FF;
    --nk-card: #FFFFFF;
    --nk-ink: #1D2142;
    --nk-muted: #6E7191;
    --nk-border: rgba(109, 61, 245, .14);
}
.stApp {
    background:
        radial-gradient(circle at 8% 8%, rgba(255,216,77,.28) 0, rgba(255,216,77,0) 26%),
        radial-gradient(circle at 90% 4%, rgba(0,166,255,.18) 0, rgba(0,166,255,0) 24%),
        linear-gradient(180deg, #FAF8FF 0%, #F3F6FF 100%);
    color: var(--nk-ink);
}
[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #6D3DF5 0%, #4E2AC8 100%);
}
[data-testid="stSidebar"] * { color: #fff !important; }
[data-testid="stSidebar"] [role="radiogroup"] label {
    border-radius: 16px;
    padding: 8px 10px;
    margin-bottom: 4px;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover {
    background: rgba(255,255,255,.12);
}
.block-container { padding-top: 1.4rem; padding-bottom: 3rem; max-width: 1280px; }
h1, h2, h3 { color: var(--nk-ink); letter-spacing: -0.03em; }
.nk-hero {
    background: linear-gradient(135deg, #6D3DF5 0%, #7B61FF 48%, #00A6FF 100%);
    border-radius: 34px;
    padding: 28px 32px;
    color: white;
    box-shadow: 0 18px 50px rgba(78,42,200,.24);
    position: relative;
    overflow: hidden;
    margin-bottom: 22px;
}
.nk-hero:before {
    content: "";
    position: absolute;
    width: 180px; height: 180px;
    background: rgba(255,216,77,.9);
    border-radius: 50%;
    right: -60px; top: -60px;
}
.nk-hero:after {
    content: "★";
    position: absolute;
    right: 76px; bottom: 26px;
    color: #FFD84D;
    font-size: 42px;
    transform: rotate(12deg);
}
.nk-hero h1 { color: white; margin: 0; font-size: 2.25rem; }
.nk-hero p { color: rgba(255,255,255,.88); margin: 8px 0 0 0; font-size: 1.02rem; max-width: 760px; }
.nk-chip-row { display:flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.nk-chip {
    background: rgba(255,255,255,.16);
    border: 1px solid rgba(255,255,255,.20);
    border-radius: 999px;
    padding: 7px 12px;
    color: #fff;
    font-weight: 700;
    font-size: .86rem;
}
.nk-card {
    background: rgba(255,255,255,.88);
    border: 1px solid var(--nk-border);
    border-radius: 26px;
    padding: 20px;
    box-shadow: 0 14px 36px rgba(58,53,123,.08);
    margin-bottom: 16px;
}
.nk-small-card {
    background: white;
    border: 1px solid var(--nk-border);
    border-radius: 22px;
    padding: 16px 18px;
    box-shadow: 0 12px 30px rgba(58,53,123,.07);
}
.nk-label { color: var(--nk-muted); font-size: .86rem; font-weight: 800; text-transform: uppercase; letter-spacing: .04em; }
.nk-value { color: var(--nk-ink); font-size: 1.8rem; line-height: 1.15; font-weight: 900; margin-top: 4px; }
.nk-help { color: var(--nk-muted); font-size: .92rem; margin-top: 6px; }
div.stButton > button, div.stDownloadButton > button {
    border-radius: 999px !important;
    border: 0 !important;
    background: linear-gradient(135deg, #FF9F2E 0%, #FFD84D 100%) !important;
    color: #291B5B !important;
    font-weight: 900 !important;
    box-shadow: 0 10px 26px rgba(255,159,46,.26) !important;
}
[data-testid="stMetric"] {
    background: #fff;
    border: 1px solid var(--nk-border);
    border-radius: 24px;
    padding: 14px 16px;
    box-shadow: 0 12px 30px rgba(58,53,123,.07);
}
[data-testid="stMetricLabel"] { color: var(--nk-muted); font-weight: 800; }
[data-testid="stMetricValue"] { color: var(--nk-ink); font-weight: 900; }
.stDataFrame, [data-testid="stDataFrame"] {
    border-radius: 22px;
    overflow: hidden;
}
.nk-status-ok { color: #188038; font-weight: 800; }
.nk-status-warn { color: #B06000; font-weight: 800; }
</style>
"""


def apply_novakid_style() -> None:
    st.markdown(NOVAKID_CSS, unsafe_allow_html=True)


def hero(title: str, subtitle: str, chips: list[str] | None = None) -> None:
    chip_html = "" if not chips else "<div class='nk-chip-row'>" + "".join([f"<span class='nk-chip'>{c}</span>" for c in chips]) + "</div>"
    st.markdown(
        f"""
        <div class="nk-hero">
            <h1>{title}</h1>
            <p>{subtitle}</p>
            {chip_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_card(title: str, text: str = "") -> None:
    st.markdown(
        f"""
        <div class="nk-card">
            <div class="nk-label">{title}</div>
            {f'<div class="nk-help">{text}</div>' if text else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def login_screen() -> None:
    st.set_page_config(page_title="Novakid Social Reports", layout="wide", page_icon="⭐")
    apply_novakid_style()
    left, mid, right = st.columns([1, 1.25, 1])
    with mid:
        hero(
            "Novakid Social Reports",
            "Войдите, чтобы загружать Meta и PR CSV, считать подписчиков и следить за CPF по регионам.",
            ["Meta + PR", "Regions", "CPF", "Team access"],
        )
        with st.form("login"):
            st.markdown("### Вход в командный кабинет")
            username = st.text_input("Логин")
            password = st.text_input("Пароль", type="password")
            submitted = st.form_submit_button("Войти", type="primary", use_container_width=True)
        if submitted:
            user = authenticate(username, password)
            if user:
                st.session_state["user"] = {"username": user["username"], "role": user["role"]}
                st.rerun()
            else:
                st.error("Неверный логин или пароль.")
        if db_df("SELECT COUNT(*) AS user_count FROM users")["user_count"].iloc[0] == 0:
            st.warning("Пользователи еще не созданы. Администратор первого запуска задается через переменные окружения.")


def require_login() -> dict:
    if "user" not in st.session_state:
        login_screen()
        st.stop()
    return st.session_state["user"]


def sidebar(user: dict) -> str:
    with st.sidebar:
        st.markdown("# ⭐ Novakid")
        st.caption("Social Reports")
        st.divider()
        st.write(f"**{user['username']}**")
        st.caption(f"role: {ROLE_LABELS.get(user['role'], user['role'])}")
        pages = []
        if has_permission(user, "view_dashboard"):
            pages.append("Dashboard")
        if has_permission(user, "upload_meta"):
            pages.append("Upload Meta")
        if has_permission(user, "upload_pr"):
            pages.append("Upload PR")
        if has_permission(user, "view_reports"):
            pages.append("Reports")
        if has_permission(user, "view_history"):
            pages.append("Upload history")
        if has_permission(user, "manage_users"):
            pages.append("Users")
        if has_permission(user, "manage_backups"):
            pages.append("Backups")
        pages.append("Profile")
        page = st.radio("Navigation", pages, label_visibility="collapsed")
        st.divider()
        if st.button("Log out", use_container_width=True):
            st.session_state.pop("user", None)
            st.rerun()
    return page


def remember_shared_filter(widget_key: str, state_key: str) -> None:
    st.session_state[state_key] = st.session_state[widget_key]


def set_period_picker_year(year: str) -> None:
    st.session_state["period_picker_year"] = year


def toggle_period(period: str) -> None:
    selected_periods = list(st.session_state.get("filter_periods", []))
    if period in selected_periods:
        selected_periods.remove(period)
    else:
        selected_periods.append(period)
    st.session_state["filter_periods"] = sorted(selected_periods, reverse=True)
    st.session_state["period_picker_year"] = period[:4]


def clear_periods() -> None:
    st.session_state["filter_periods"] = []


def apply_date_filter(df: pd.DataFrame, selected_periods: list[str]) -> pd.DataFrame:
    if not selected_periods:
        return df.iloc[0:0]
    return df[df["month"].isin(selected_periods)]


def period_picker(container, available_periods: list[str]) -> list[str]:
    years = sorted({period[:4] for period in available_periods})
    selected_periods = st.session_state["filter_periods"]
    if not years:
        container.button("Periods: Choose periods", disabled=True, use_container_width=True)
        return []

    if "period_picker_year" not in st.session_state or st.session_state["period_picker_year"] not in years:
        st.session_state["period_picker_year"] = selected_periods[0][:4] if selected_periods else years[-1]

    if len(selected_periods) == 1:
        selected_period = selected_periods[0]
        selected_label = f"{MONTH_NAMES[selected_period[5:7]]} {selected_period[:4]}"
    elif selected_periods:
        selected_label = f"{len(selected_periods)} periods"
    else:
        selected_label = "Choose periods"

    with container.popover(f"Periods: {selected_label}", use_container_width=True):
        picker_year = st.session_state["period_picker_year"]
        year_index = years.index(picker_year)
        prev_col, year_col, next_col = st.columns([1, 2, 1])
        prev_col.button(
            "‹",
            key="period_previous_year",
            disabled=year_index == 0,
            on_click=set_period_picker_year,
            args=(years[max(0, year_index - 1)],),
            use_container_width=True,
        )
        year_col.markdown(f"<h4 style='text-align:center;margin:6px 0'>{picker_year}</h4>", unsafe_allow_html=True)
        next_col.button(
            "›",
            key="period_next_year",
            disabled=year_index == len(years) - 1,
            on_click=set_period_picker_year,
            args=(years[min(len(years) - 1, year_index + 1)],),
            use_container_width=True,
        )

        month_columns = st.columns(3)
        for index, (month_number, month_name) in enumerate(MONTH_NAMES.items()):
            period = f"{picker_year}-{month_number}"
            month_columns[index % 3].button(
                f"✓ {month_name}" if period in selected_periods else month_name,
                key=f"period_{period}",
                disabled=period not in available_periods,
                on_click=toggle_period,
                args=(period,),
                use_container_width=True,
            )
        st.button(
            "Clear periods",
            key="clear_period",
            disabled=not selected_periods,
            on_click=clear_periods,
            use_container_width=True,
        )
    return st.session_state["filter_periods"]


def shared_results_filters(df: pd.DataFrame) -> tuple[list[str], list[str], bool]:
    accounts = sorted(df["account"].dropna().unique().tolist())
    available_periods = sorted(df["month"].dropna().astype(str).unique().tolist(), reverse=True)
    defaults = {
        "filter_accounts": [],
        "filter_periods": [],
        "filter_warnings": False,
    }
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default

    legacy_period = st.session_state.pop("filter_period", None)
    if legacy_period:
        if not st.session_state["filter_periods"]:
            st.session_state["filter_periods"] = [legacy_period]

    st.session_state["filter_accounts"] = [
        account for account in st.session_state["filter_accounts"] if account in accounts
    ]
    st.session_state["filter_periods"] = [
        period for period in st.session_state["filter_periods"] if period in available_periods
    ]

    st.session_state["_filter_accounts"] = st.session_state["filter_accounts"]
    st.session_state["_filter_warnings"] = st.session_state["filter_warnings"]

    c1, c2, c3 = st.columns([1.3, 1.1, .9])
    selected_accounts = c1.multiselect(
        "Region / account",
        accounts,
        key="_filter_accounts",
        on_change=remember_shared_filter,
        args=("_filter_accounts", "filter_accounts"),
    )
    selected_periods = period_picker(c2, available_periods)
    only_warnings = c3.checkbox(
        "Only warnings",
        key="_filter_warnings",
        on_change=remember_shared_filter,
        args=("_filter_warnings", "filter_warnings"),
    )
    return selected_accounts, selected_periods, only_warnings


def page_dashboard() -> None:
    user = st.session_state.get("user")
    if not has_permission(user, "view_dashboard"):
        st.error("У вас нет прав для просмотра Dashboard.")
        return
    hero(
        "Dashboard",
        "Обзор подписчиков, затрат и CPF по всем регионам Novakid. Используйте фильтры, чтобы смотреть отдельные аккаунты или месяцы.",
        ["Followers", "Spend", "CPF", "Warnings"],
    )
    df = db_df("SELECT * FROM final_results ORDER BY period_start DESC, account, final_followers DESC")
    if df.empty:
        st.info("Пока нет данных. Загрузите Meta CSV, затем PR CSV при наличии.")
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
        st.warning(f"Есть строки для проверки: {warning_count}")

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

        st.markdown("### Top publications")
        top = f.sort_values("final_followers", ascending=False).head(12)
        st.dataframe(
            top[["account", "month", "publication_id", "publication_link", "final_followers", "spend_usd", "cpf_usd", "warning"]],
            use_container_width=True,
            hide_index=True,
            column_config={"publication_link": st.column_config.LinkColumn("Link")},
        )


def page_upload_meta(user: dict) -> None:
    if not has_permission(user, "upload_meta"):
        st.error("У вас нет прав для загрузки Meta CSV.")
        return
    hero(
        "Upload Meta",
        "Загрузите CSV из Meta Business Suite. Русские и английские выгрузки распределяются по аккаунтам через username.",
        ["RU/EN columns", "Combined exports", "1+ followers only", "Post links"],
    )
    meta_file = st.file_uploader("CSV из Meta Business Suite", type=["csv"], key="meta")
    c1, c2 = st.columns(2)
    manual_start = c1.date_input("Начало периода, если не определяется из имени файла", value=None)
    manual_end = c2.date_input("Конец периода, если не определяется из имени файла", value=None)
    if meta_file:
        try:
            preview = read_csv_any(meta_file)
            accs = infer_accounts_from_meta(preview)
            st.success("Найденные аккаунты: " + (", ".join(accs) if accs else "не удалось определить"))
            st.dataframe(preview.head(10), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(str(exc))
    if st.button("Save Meta and recalculate", type="primary", use_container_width=True):
        if not meta_file:
            st.error("Загрузите CSV.")
        else:
            try:
                rows, warnings = import_meta(meta_file, user, manual_start, manual_end)
                st.success(f"Meta сохранена. Строк: {rows}. Отчет пересчитан автоматически.")
                for w in warnings:
                    st.warning(w)
            except Exception as exc:
                st.error(str(exc))


def page_upload_pr(user: dict) -> None:
    if not has_permission(user, "upload_pr"):
        st.error("У вас нет прав для загрузки PR CSV.")
        return
    hero(
        "Upload PR",
        "Таргетолог загружает CSV из рекламного кабинета. Система распределит общий PR-файл по аккаунтам через ID публикации из Meta.",
        ["Auto account distribution", "Spend", "CPF", "Auto recalc"],
    )
    auto_detect = st.checkbox("Автоматически распределить по аккаунтам через ID публикации из Meta", value=True)
    existing = accounts_in_db()
    default_options = existing + ["novakid_israel", "novakid_france", "novakid_spain", "novakid_turkey"]
    default_options = sorted(set(default_options))
    account = ""
    if not auto_detect:
        selected = st.selectbox("Region / account", default_options, index=0 if default_options else None)
        custom = st.text_input("Или введите новый аккаунт вручную", placeholder="novakid_germany")
        account = custom.strip() or selected
    pr_file = st.file_uploader("CSV из Novakid PR", type=["csv"], key="pr")
    if pr_file:
        try:
            preview = read_csv_any(pr_file)
            st.dataframe(preview.head(10), use_container_width=True, hide_index=True)
        except Exception as exc:
            st.error(str(exc))
    if st.button("Save PR and recalculate", type="primary", use_container_width=True):
        if not pr_file:
            st.error("Загрузите CSV.")
        else:
            try:
                rows, warnings = import_pr(pr_file, user, account, auto_detect)
                target = "по аккаунтам из Meta" if auto_detect else f"для {account}"
                st.success(f"PR сохранен {target}. Строк: {rows}. Отчет пересчитан автоматически.")
                for w in warnings:
                    st.warning(w)
            except Exception as exc:
                st.error(str(exc))


def filtered_results_ui() -> pd.DataFrame:
    df = db_df("SELECT * FROM final_results ORDER BY period_start DESC, account, final_followers DESC")
    if df.empty:
        return df
    selected_accounts, selected_periods, only_warnings = shared_results_filters(df)
    f = df[df["account"].isin(selected_accounts)] if selected_accounts else df.iloc[0:0]
    f = latest_publications_df(f)
    f = apply_date_filter(f, selected_periods)
    if only_warnings:
        f = f[f["warning"].fillna("") != ""]
    return f


def page_report(user: dict) -> None:
    if not has_permission(user, "view_reports"):
        st.error("У вас нет прав для просмотра отчетов.")
        return
    hero(
        "Reports",
        "Финальная таблица после матчинга Meta + PR. Для выбранных строк можно вручную уточнить подписчиков из рекламного кабинета.",
        ["Meta followers - PR followers", "Manual PR override", "Export CSV / Excel"],
    )
    f = filtered_results_ui()
    if f.empty:
        st.info("Пока нет финальных данных или фильтры ничего не нашли.")
        return

    total_followers = int(f["final_followers"].sum())
    total_spend = float(f["spend_usd"].sum())
    total_pr = int(f["pr_followers"].sum())
    cpf = total_spend / total_pr if total_pr > 0 else None
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rows", f"{len(f):,}")
    c2.metric("Final followers", f"{total_followers:,}")
    c3.metric("Spend", f"${total_spend:,.2f}")
    c4.metric("CPF", "—" if cpf is None else f"${cpf:,.2f}")

    if has_permission(user, "edit_reports"):
        st.markdown("### Ручное уточнение подписчиков из рекламного кабинета")
        st.caption(
            "Сначала отметьте нужные строки. Они появятся в отдельном блоке сверху, где можно указать фактическое число подписчиков PR. "
            "Строки с предупреждением выбраны автоматически. "
            "Чтобы вернуть значение из CSV, очистите ручное поле и сохраните строку."
        )
        selection_cols = [
            "Выбрать", "account", "publication_date", "publication_id", "publication_link",
            "post_reach", "meta_followers", "pr_followers", "final_followers", "warning", "period_start", "period_end",
        ]
        selection_data = f.copy()
        selection_data.insert(0, "Выбрать", selection_data["warning"].fillna("") != "")
        selected_rows_container = st.container()

        st.markdown("#### Все строки")
        selected_rows = st.data_editor(
            selection_data[selection_cols],
            use_container_width=True,
            hide_index=True,
            disabled=[c for c in selection_cols if c != "Выбрать"],
            column_config={
                "Выбрать": st.column_config.CheckboxColumn("Выбрать", help="Добавить строку в блок ручного ввода"),
                "account": "Аккаунт",
                "publication_date": "Дата публикации",
                "publication_id": "ID публикации",
                "publication_link": st.column_config.LinkColumn("Ссылка"),
                "post_reach": "Охват поста",
                "meta_followers": "Подписчики Meta",
                "pr_followers": "PR для расчёта",
                "final_followers": "Итог подписчиков",
                "warning": "Комментарий",
                "period_start": None,
                "period_end": None,
            },
            key="followers_override_selector",
        )
        selected_rows = selected_rows[selected_rows["Выбрать"] == True].copy()  # noqa: E712

        with selected_rows_container:
            st.markdown("#### Выбранные строки для ручного ввода")
            if selected_rows.empty:
                st.info("Отметьте строки в списке ниже. Строки с предупреждением отмечаются автоматически.")
            else:
                selected_keys = ["account", "period_start", "period_end", "publication_id"]
                selected_source = f.merge(selected_rows[selected_keys], on=selected_keys, how="inner")
                selected_editor_cols = [
                    "account", "publication_date", "publication_id", "publication_link",
                    "post_reach", "meta_followers", "imported_pr_followers", "manual_pr_followers", "pr_followers",
                    "final_followers", "warning", "period_start", "period_end",
                ]
                edited = st.data_editor(
                    selected_source[selected_editor_cols],
                    use_container_width=True,
                    hide_index=True,
                    disabled=[c for c in selected_editor_cols if c != "manual_pr_followers"],
                    column_config={
                        "account": "Аккаунт",
                        "publication_date": "Дата публикации",
                        "publication_id": "ID публикации",
                        "publication_link": st.column_config.LinkColumn("Ссылка"),
                        "post_reach": "Охват поста",
                        "meta_followers": "Подписчики Meta",
                        "imported_pr_followers": "PR из CSV",
                        "manual_pr_followers": st.column_config.NumberColumn(
                            "PR вручную", min_value=0, step=1, format="%d",
                            help="Пусто — использовать значение из CSV",
                        ),
                        "pr_followers": "PR для расчёта",
                        "final_followers": "Итог подписчиков",
                        "warning": "Комментарий",
                        "period_start": None,
                        "period_end": None,
                    },
                    key="followers_override_editor",
                )
                if st.button("Сохранить ручные значения и пересчитать", type="primary", use_container_width=True):
                    try:
                        edited.insert(0, "Изменить", True)
                        changed = save_follower_overrides(edited, user)
                        st.success(f"Сохранено строк: {changed}. Отчет пересчитан.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))
    else:
        st.info("Режим просмотра: ваша роль не позволяет менять ручные значения.")

    st.markdown("### Финальный отчет")
    display_cols = [
        "account", "month", "publication_date", "publication_id", "publication_link",
        "post_reach", "meta_followers", "pr_followers", "final_followers", "spend_usd", "cpf_usd",
        "meta_uploaded_by", "pr_uploaded_by", "override_updated_by", "updated_at",
    ]
    final_report = f[display_cols]
    st.dataframe(
        final_report,
        use_container_width=True,
        hide_index=True,
        column_config={
            "publication_link": st.column_config.LinkColumn("Ссылка на публикацию"),
            "account": "Аккаунт",
            "month": "Месяц",
            "publication_date": "Дата публикации",
            "publication_id": "ID публикации",
            "post_reach": "Охват поста",
            "meta_followers": "Подписчики Meta",
            "pr_followers": "Подписчики PR для расчёта",
            "final_followers": "Итог подписчиков",
            "spend_usd": st.column_config.NumberColumn("Spend, USD", format="$%.2f"),
            "cpf_usd": st.column_config.NumberColumn("CPF, USD", format="$%.2f"),
            "meta_uploaded_by": "Meta загрузил",
            "pr_uploaded_by": "PR загрузил",
            "override_updated_by": "Ручное значение обновил",
            "updated_at": "Обновлено",
        },
    )
    csv_col, excel_col = st.columns(2)
    csv_col.download_button(
        "Download report CSV",
        data=final_report.to_csv(index=False).encode("utf-8-sig"),
        file_name="instagram_followers_report.csv",
        mime="text/csv",
        use_container_width=True,
    )
    excel_col.download_button(
        "Download report Excel",
        data=dataframe_to_excel_bytes(final_report),
        file_name="instagram_followers_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def page_upload_history() -> None:
    user = st.session_state.get("user")
    if not has_permission(user, "view_history"):
        st.error("У вас нет прав для просмотра истории загрузок.")
        return
    hero("Upload history", "Кто, когда и какие файлы загружал. Это помогает проверять актуальность отчетов.", ["Audit", "Files", "Rows saved"])
    df = db_df("SELECT file_type, account, period_start, period_end, filename, uploaded_by, uploaded_at, rows_saved, warnings FROM uploads ORDER BY uploaded_at DESC")
    if df.empty:
        st.info("Загрузок пока нет.")
    else:
        st.dataframe(df, use_container_width=True, hide_index=True)


def page_profile(user: dict) -> None:
    hero("Profile", "Смена личного пароля пользователя.", ["Security"])
    with st.form("change_my_password"):
        old = st.text_input("Старый пароль", type="password")
        new = st.text_input("Новый пароль", type="password")
        ok = st.form_submit_button("Сменить пароль", use_container_width=True)
    if ok:
        current = get_user(user["username"])
        if current and verify_password(old, current["password_hash"]) and len(new) >= 8:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("UPDATE users SET password_hash=? WHERE username=?", (hash_password(new), user["username"]))
                conn.commit()
            st.success("Пароль обновлен.")
        else:
            st.error("Проверьте старый пароль. Новый пароль должен быть минимум 8 символов.")


def page_users(user: dict) -> None:
    if not has_permission(user, "manage_users"):
        st.error("У вас нет прав для управления пользователями.")
        return

    hero("Users", "Админка для создания, изменения и удаления пользователей.", ["Admin", "Roles", "Passwords"])
    df = db_df("SELECT username, role, is_active, created_at FROM users ORDER BY username")
    st.dataframe(df, use_container_width=True, hide_index=True)

    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("Создать пользователя")
        with st.form("create_user"):
            username = st.text_input("Логин нового пользователя")
            password = st.text_input("Пароль", type="password")
            role = st.selectbox("Роль", ROLES, format_func=lambda value: ROLE_LABELS[value])
            submitted = st.form_submit_button("Создать", use_container_width=True)
        if submitted:
            if not username.strip() or len(password) < 8:
                st.error("Укажите логин и пароль минимум 8 символов.")
            elif role not in ROLES:
                st.error("Выберите корректную роль.")
            else:
                try:
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute(
                            "INSERT INTO users(username,password_hash,role,is_active,created_at) VALUES(?,?,?,?,?)",
                            (username.strip(), hash_password(password), role, 1, now_utc()),
                        )
                        conn.commit()
                    st.success("Пользователь создан.")
                    st.rerun()
                except sqlite3.IntegrityError:
                    st.error("Такой пользователь уже есть.")
    with c2:
        st.subheader("Редактировать пользователя")
        users = db_df("SELECT username FROM users ORDER BY username")["username"].tolist()
        with st.form("edit_user"):
            target = st.selectbox("Пользователь", users)
            current = get_user(target) if target else None
            current_role = current["role"] if current else ROLE_VIEWER
            current_active = bool(current["is_active"]) if current else True
            role = st.selectbox(
                "Роль",
                ROLES,
                index=ROLES.index(current_role) if current_role in ROLES else 0,
                format_func=lambda value: ROLE_LABELS[value],
            )
            is_active = st.checkbox("Активен", value=current_active)
            ok = st.form_submit_button("Сохранить", use_container_width=True)
        if ok:
            if target == user["username"] and (role != user["role"] or not is_active):
                st.error("Нельзя изменить собственную роль или отключить собственную учетную запись.")
            else:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("UPDATE users SET role=?, is_active=? WHERE username=?", (role, int(is_active), target))
                    conn.commit()
                st.success("Пользователь обновлен.")
                st.rerun()
    with c3:
        st.subheader("Пароль и удаление")
        users = db_df("SELECT username FROM users ORDER BY username")["username"].tolist()
        with st.form("reset_password"):
            target = st.selectbox("Пользователь", users, key="password_target")
            new_pass = st.text_input("Новый пароль", type="password")
            ok = st.form_submit_button("Обновить пароль", use_container_width=True)
        if ok:
            if len(new_pass) < 8:
                st.error("Пароль должен быть минимум 8 символов.")
            else:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("UPDATE users SET password_hash=? WHERE username=?", (hash_password(new_pass), target))
                    conn.commit()
                st.success("Пароль обновлен.")

        with st.form("delete_user"):
            target = st.selectbox("Пользователь", users, key="delete_target")
            confirm = st.checkbox("Подтверждаю удаление пользователя")
            delete_ok = st.form_submit_button("Удалить пользователя", use_container_width=True)
        if delete_ok:
            if target == user["username"]:
                st.error("Нельзя удалить собственную учетную запись.")
            elif not confirm:
                st.error("Подтвердите удаление.")
            else:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("DELETE FROM users WHERE username=?", (target,))
                    conn.commit()
                st.success("Пользователь удален.")
                st.rerun()


def page_backups(user: dict) -> None:
    if not has_permission(user, "manage_backups"):
        st.error("У вас нет прав для управления резервными копиями.")
        return

    hero(
        "Backups",
        "Резервные копии SQLite создаются автоматически раз в неделю. Администратор может создать и скачать копию вручную.",
        ["Weekly", f"Keep last {BACKUP_RETENTION}", "SQLite snapshot"],
    )
    last_backup = get_setting("last_weekly_backup_at")
    st.caption(f"Backup directory: {BACKUP_DIR}")
    st.caption(f"Last scheduled/manual backup: {last_backup or 'never'}")

    if st.button("Create Backup", type="primary", use_container_width=True):
        try:
            backup_path = create_manual_backup(user)
            st.success(f"Backup created: {backup_path.name}")
            st.rerun()
        except Exception as exc:
            st.error(f"Backup failed: {exc}")

    backups = list_backups()
    if not backups:
        st.info("Резервных копий пока нет.")
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

    st.markdown("### Download Backup")
    selected_name = st.selectbox("Backup file", [backup["name"] for backup in backups])
    selected = next(backup for backup in backups if backup["name"] == selected_name)
    st.download_button(
        "Download Backup",
        data=selected["path"].read_bytes(),
        file_name=selected["name"],
        mime="application/octet-stream",
        use_container_width=True,
    )


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
