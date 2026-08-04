from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from core.config import DB_PATH, now_utc
from integrations.facebook_ads_client import (
    FacebookApiError,
    get_ad_creative,
    get_ads,
    get_campaigns,
    get_insights,
)

INSIGHTS_LOOKBACK_DAYS = 30


@dataclass
class SyncResult:
    account_id: str
    campaigns: int = 0
    ads: int = 0
    creatives: int = 0
    insight_rows: int = 0
    status: str = "ok"
    message: str = ""


def _log_start(conn: sqlite3.Connection, account_id: str) -> int:
    cur = conn.execute(
        "INSERT INTO fb_sync_log(account_id, started_at, status) VALUES(?,?,?)",
        (account_id, now_utc(), "running"),
    )
    conn.commit()
    return cur.lastrowid


def _log_finish(conn: sqlite3.Connection, log_id: int, status: str, message: str) -> None:
    conn.execute(
        "UPDATE fb_sync_log SET finished_at=?, status=?, message=? WHERE id=?",
        (now_utc(), status, message, log_id),
    )
    conn.commit()


def sync_ad_account(account_id: str) -> SyncResult:
    result = SyncResult(account_id=account_id)
    with sqlite3.connect(DB_PATH) as conn:
        log_id = _log_start(conn, account_id)
        try:
            updated_at = now_utc()

            campaigns = get_campaigns(account_id)
            for campaign in campaigns:
                conn.execute(
                    """
                    INSERT INTO fb_campaigns(campaign_id, account_id, name, objective, status, created_time, updated_at)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(campaign_id) DO UPDATE SET
                        account_id=excluded.account_id,
                        name=excluded.name,
                        objective=excluded.objective,
                        status=excluded.status,
                        created_time=excluded.created_time,
                        updated_at=excluded.updated_at
                    """,
                    (
                        campaign["id"], account_id, campaign.get("name"), campaign.get("objective"),
                        campaign.get("status"), campaign.get("created_time"), updated_at,
                    ),
                )
            result.campaigns = len(campaigns)

            all_ad_ids: list[str] = []
            for campaign in campaigns:
                ads = get_ads(campaign["id"])
                for ad in ads:
                    conn.execute(
                        """
                        INSERT INTO fb_ads(ad_id, campaign_id, adset_id, name, status, updated_at)
                        VALUES(?,?,?,?,?,?)
                        ON CONFLICT(ad_id) DO UPDATE SET
                            campaign_id=excluded.campaign_id,
                            adset_id=excluded.adset_id,
                            name=excluded.name,
                            status=excluded.status,
                            updated_at=excluded.updated_at
                        """,
                        (ad["id"], campaign["id"], ad.get("adset_id"), ad.get("name"), ad.get("status"), updated_at),
                    )
                    all_ad_ids.append(ad["id"])
            result.ads = len(all_ad_ids)

            for ad_id in all_ad_ids:
                creative = get_ad_creative(ad_id)
                if not creative:
                    continue
                conn.execute(
                    """
                    INSERT INTO fb_creatives(creative_id, ad_id, title, body, image_url, thumbnail_url, video_id, updated_at)
                    VALUES(?,?,?,?,?,?,?,?)
                    ON CONFLICT(creative_id) DO UPDATE SET
                        ad_id=excluded.ad_id,
                        title=excluded.title,
                        body=excluded.body,
                        image_url=excluded.image_url,
                        thumbnail_url=excluded.thumbnail_url,
                        video_id=excluded.video_id,
                        updated_at=excluded.updated_at
                    """,
                    (
                        creative["id"], ad_id, creative.get("title"), creative.get("body"),
                        creative.get("image_url"), creative.get("thumbnail_url"), creative.get("video_id"), updated_at,
                    ),
                )
                result.creatives += 1

            until = date.today()
            since = until - timedelta(days=INSIGHTS_LOOKBACK_DAYS)
            insights = get_insights(account_id, since.isoformat(), until.isoformat())
            for row in insights:
                conn.execute(
                    """
                    INSERT INTO fb_insights(ad_id, date_start, date_stop, spend, impressions, reach, clicks)
                    VALUES(?,?,?,?,?,?,?)
                    ON CONFLICT(ad_id, date_start, date_stop) DO UPDATE SET
                        spend=excluded.spend,
                        impressions=excluded.impressions,
                        reach=excluded.reach,
                        clicks=excluded.clicks
                    """,
                    (
                        row["ad_id"], row["date_start"], row["date_stop"],
                        float(row.get("spend", 0) or 0), int(row.get("impressions", 0) or 0),
                        int(row.get("reach", 0) or 0), int(row.get("clicks", 0) or 0),
                    ),
                )
            result.insight_rows = len(insights)

            conn.commit()
            result.status = "ok"
            result.message = (
                f"{result.campaigns} campaigns, {result.ads} ads, "
                f"{result.creatives} creatives, {result.insight_rows} insight rows"
            )
            _log_finish(conn, log_id, "ok", result.message)
        except FacebookApiError as exc:
            conn.rollback()
            result.status = "error"
            result.message = str(exc)
            _log_finish(conn, log_id, "error", result.message)
        except Exception as exc:
            conn.rollback()
            result.status = "error"
            result.message = f"Unexpected error: {exc}"
            _log_finish(conn, log_id, "error", result.message)
    return result


def sync_all_active_accounts() -> list[SyncResult]:
    with sqlite3.connect(DB_PATH) as conn:
        account_ids = [
            row[0]
            for row in conn.execute("SELECT account_id FROM fb_ad_accounts WHERE is_active=1").fetchall()
        ]
    return [sync_ad_account(account_id) for account_id in account_ids]


def last_sync_for_account(account_id: str) -> Optional[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            """
            SELECT started_at, finished_at, status, message
            FROM fb_sync_log
            WHERE account_id=?
            ORDER BY started_at DESC
            LIMIT 1
            """,
            (account_id,),
        ).fetchone()
        return dict(row) if row else None
