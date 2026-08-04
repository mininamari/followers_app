from __future__ import annotations

import io
import re
import sqlite3
from datetime import datetime, date
from typing import Optional

import pandas as pd

from core.auth import require_permission
from core.config import (
    DB_PATH,
    UPLOAD_DIR,
    META_ID_COL,
    META_FOLLOWERS_COL,
    META_LINK_COL,
    META_REACH_COL,
    META_ACCOUNT_USERNAME_COL,
    META_ACCOUNT_NAME_COL,
    META_PUBLISHED_AT_COL,
    META_COLUMN_ALIASES,
    PR_START_COL,
    PR_END_COL,
    PR_AD_NAME_COL,
    PR_FOLLOWERS_COL,
    PR_SPEND_COL,
    PR_COLUMN_ALIASES,
    REQUIRED_META,
    REQUIRED_PR,
    now_utc,
)
from core.i18n import tr


# -------------------- generic helpers --------------------

def is_novakid_account(account: object) -> bool:
    return str(account).strip().lstrip("@").lower().startswith("novakid")


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
        raise ValueError(tr(f"Could not parse period date: {value}", f"Не удалось распознать дату периода: {value}"))
    return dt.date().isoformat()


def normalize_publication_date(value) -> str:
    dt = pd.to_datetime(value, errors="coerce", dayfirst=False)
    if pd.isna(dt):
        dt = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(dt):
        raise ValueError(tr(f"Could not parse publication date: {value}", f"Не удалось распознать дату публикации: {value}"))
    return dt.date().isoformat()


def month_from_period(period_start: str) -> str:
    return period_start[:7]


def validate_columns(df: pd.DataFrame, required: list[str], file_label: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(tr(f"The {file_label} file is missing columns: {', '.join(missing)}", f"В файле {file_label} нет колонок: {', '.join(missing)}"))


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


def normalize_pr_columns(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    rename_map = {}
    used_aliases = []
    normalized_columns = {str(column).strip().casefold(): column for column in df.columns}
    for canonical, aliases in PR_COLUMN_ALIASES.items():
        if canonical in df.columns:
            continue
        for alias in aliases:
            source_column = normalized_columns.get(alias.casefold())
            if source_column:
                rename_map[source_column] = canonical
                used_aliases.append(f"{source_column} -> {canonical}")
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
    raise ValueError(tr("Could not read the CSV. Check the encoding and file format.", "Не удалось прочитать CSV. Проверьте кодировку и формат файла."))


def save_uploaded_file(uploaded_file, file_type: str, data: Optional[bytes] = None) -> str:
    safe_name = re.sub(r"[^A-Za-zА-Яа-я0-9_.() -]+", "_", uploaded_file.name)
    target = UPLOAD_DIR / file_type / datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    target.mkdir(parents=True, exist_ok=True)
    path = target / safe_name
    with path.open("wb") as f:
        f.write(uploaded_file.getvalue() if data is None else data)
    return str(path)


def dataframe_to_excel_bytes(df: pd.DataFrame) -> bytes:
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Report")
    return output.getvalue()


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
                warning = tr("Follower count became negative. Check Meta/Novakid PR data.", "Получилось отрицательное значение подписчиков. Нужно проверить Meta/Novakid PR.")
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
        raise ValueError(tr("Select rows where a manual value should be saved.", "Отметьте строки, для которых нужно сохранить ручное значение."))

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
                    raise ValueError(tr("Manual follower count cannot be negative.", "Ручное количество подписчиков не может быть отрицательным."))
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


# -------------------- Import logic --------------------

def import_meta(uploaded_file, user: dict, manual_start: Optional[date], manual_end: Optional[date]) -> tuple[int, list[str]]:
    require_permission(user, "upload_meta")
    df = read_csv_any(uploaded_file)
    df, used_aliases = normalize_meta_columns(df)
    validate_columns(df, REQUIRED_META, "Meta Business Suite")
    period = parse_meta_period_from_filename(uploaded_file.name)
    warnings: list[str] = []
    if used_aliases:
        warnings.append(tr("Meta columns were recognized by English names: ", "Meta-колонки распознаны по английским названиям: ") + ", ".join(used_aliases) + ".")
    if period:
        period_start, period_end = period
    elif manual_start and manual_end:
        period_start, period_end = manual_start.isoformat(), manual_end.isoformat()
        warnings.append(tr("Meta period was taken from manual input because it could not be detected from the filename.", "Период Meta взят из ручного ввода, потому что его не удалось определить из имени файла."))
    else:
        raise ValueError(tr("Could not detect the Meta period from the filename. Enter dates manually.", "Не удалось определить период Meta из имени файла. Укажите даты вручную."))

    if period_start > period_end:
        raise ValueError(tr("Period start date is after the end date.", "Дата начала периода больше даты окончания."))

    df = df.copy()
    df[META_ID_COL] = df[META_ID_COL].apply(clean_id)
    df[META_PUBLISHED_AT_COL] = df[META_PUBLISHED_AT_COL].apply(normalize_publication_date)
    df[META_FOLLOWERS_COL] = to_number(df[META_FOLLOWERS_COL]).astype(int)
    if META_REACH_COL not in df.columns:
        df[META_REACH_COL] = 0
        warnings.append(tr("The Meta file has no reach column; publications were saved with reach 0.", "В Meta-файле нет колонки охвата; для публикаций сохранено значение 0."))
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
            tr(f"Skipped blogger accounts ({len(skipped_accounts)}): ", f"Пропущены аккаунты блогеров ({len(skipped_accounts)}): ")
            + ", ".join(skipped_accounts[:10])
            + (tr(f" and {len(skipped_accounts) - 10} more.", " и другие.") if len(skipped_accounts) > 10 else ".")
        )
    if df.empty:
        raise ValueError(tr("The Meta file has no Novakid publications with 1+ follower.", "В Meta-файле нет публикаций Novakid с 1+ подписчиком."))

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
        raise ValueError(tr("Choose an account for the PR file, for example novakid_israel.", "Для PR-файла нужно выбрать аккаунт, например novakid_israel."))
    account = account.strip()
    if not auto_detect_accounts and not is_novakid_account(account):
        raise ValueError(tr("Data can only be saved for Novakid accounts.", "Можно сохранять данные только для аккаунтов Novakid."))
    df = read_csv_any(uploaded_file)
    df, used_aliases = normalize_pr_columns(df)
    validate_columns(df, REQUIRED_PR, "Novakid PR")
    warnings: list[str] = []
    if used_aliases:
        warnings.append(tr("PR columns were recognized by alternative names: ", "PR-колонки распознаны по альтернативным названиям: ") + ", ".join(used_aliases) + ".")
    df = df.copy()
    df[PR_START_COL] = df[PR_START_COL].apply(normalize_period)
    df[PR_END_COL] = df[PR_END_COL].apply(normalize_period)
    starts = sorted(df[PR_START_COL].dropna().unique())
    ends = sorted(df[PR_END_COL].dropna().unique())
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError(tr("Multiple periods were found in Novakid PR. Upload a file for one period only.", "В Novakid PR найдено несколько периодов. Загрузите файл только за один период."))
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
        raise ValueError(tr("Novakid PR has no rows with a filled ad name.", "В Novakid PR нет строк с заполненным названием объявления."))

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
            raise ValueError(tr("No PR-to-Meta matches were found by publication ID for this period.", "Не найдено совпадений PR с Meta по ID публикации за этот период."))

        account_counts = meta_matches.groupby("publication_id")["account"].nunique()
        ambiguous_ids = set(account_counts[account_counts > 1].index.astype(str))
        matched_once = meta_matches[~meta_matches["publication_id"].isin(ambiguous_ids)].copy()
        grouped = grouped.merge(matched_once, on="publication_id", how="left")

        unmatched_ids = grouped.loc[grouped["account"].isna(), "publication_id"].astype(str).tolist()
        excluded_ids = sorted(set(unmatched_ids) | ambiguous_ids)
        if excluded_ids:
            preview = ", ".join(excluded_ids[:25])
            extra = "" if len(excluded_ids) <= 25 else tr(f" and {len(excluded_ids) - 25} more", f" и еще {len(excluded_ids) - 25}")
            warnings.append(
                tr("Excluded PR rows without an unambiguous Meta match by publication ID: ", "Исключены строки PR без однозначного совпадения с Meta по ID публикации: ")
                + f"{preview}{extra}."
            )

        grouped = grouped[grouped["account"].notna()].copy()
        if grouped.empty:
            raise ValueError(tr("After excluding unmatched IDs, there are no PR rows left to save.", "После исключения несовпавших ID не осталось строк PR для сохранения."))
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
