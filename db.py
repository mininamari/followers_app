from __future__ import annotations

import io
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd

from core.auth import hash_password, require_permission
from core.config import (
    BACKUP_DIR,
    BACKUP_INTERVAL_DAYS,
    BACKUP_RETENTION,
    DB_PATH,
    META_ACCOUNT_USERNAME_COL,
    META_ID_COL,
    META_REACH_COL,
    ROLE_ADMIN,
    ROLES,
    UPLOAD_DIR,
    now_utc,
    parse_utc,
)
from core.csv_import import clean_id, is_novakid_account, normalize_meta_columns, read_csv_any, to_number


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
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fb_ad_accounts (
                account_id TEXT PRIMARY KEY,
                label TEXT,
                novakid_account TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fb_campaigns (
                campaign_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL,
                name TEXT,
                objective TEXT,
                status TEXT,
                created_time TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fb_ads (
                ad_id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                adset_id TEXT,
                name TEXT,
                status TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fb_creatives (
                creative_id TEXT PRIMARY KEY,
                ad_id TEXT NOT NULL,
                title TEXT,
                body TEXT,
                image_url TEXT,
                thumbnail_url TEXT,
                video_id TEXT,
                tags TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fb_insights (
                ad_id TEXT NOT NULL,
                date_start TEXT NOT NULL,
                date_stop TEXT NOT NULL,
                spend REAL NOT NULL DEFAULT 0,
                impressions INTEGER NOT NULL DEFAULT 0,
                reach INTEGER NOT NULL DEFAULT 0,
                clicks INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(ad_id, date_start, date_stop)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fb_sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                message TEXT
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

    creative_cols = {row[1] for row in conn.execute("PRAGMA table_info(fb_creatives)")}
    if "tags" not in creative_cols:
        conn.execute("ALTER TABLE fb_creatives ADD COLUMN tags TEXT")
    conn.commit()


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
