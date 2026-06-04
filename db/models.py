"""データベースモデル・CRUD関数。"""
import json
import sqlite3
from contextlib import contextmanager
from typing import Generator

from config import Config


@contextmanager
def get_conn(db_path: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """SQLite接続コンテキストマネージャ。commit/rollbackを自動制御する。"""
    path = db_path or Config.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─── viewer_areas ─────────────────────────────────────────────────────────────

def get_viewer_areas(viewer_id: str, db_path: str | None = None) -> list[dict]:
    """指定viewer_idの登録地域一覧を優先度順で返す。"""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM viewer_areas WHERE viewer_id = ? ORDER BY priority DESC, id ASC",
            (viewer_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def upsert_viewer_area(
    viewer_id: str,
    pref_code: str,
    area_code: str,
    name: str,
    priority: int = 0,
    db_path: str | None = None,
) -> None:
    """地域設定をupsertする（既存はpriority・nameを更新）。"""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO viewer_areas (viewer_id, pref_code, area_code, name, priority)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(viewer_id, area_code)
            DO UPDATE SET pref_code=excluded.pref_code, name=excluded.name, priority=excluded.priority
            """,
            (viewer_id, pref_code, area_code, name, priority),
        )


def delete_viewer_area(viewer_id: str, area_code: str, db_path: str | None = None) -> None:
    """指定地域設定を削除する。"""
    with get_conn(db_path) as conn:
        conn.execute(
            "DELETE FROM viewer_areas WHERE viewer_id = ? AND area_code = ?",
            (viewer_id, area_code),
        )


def get_all_pref_codes(db_path: str | None = None) -> list[str]:
    """登録済みの都道府県コード一覧（重複なし）を返す。"""
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT pref_code FROM viewer_areas").fetchall()
        return [r["pref_code"] for r in rows]


# ─── quakes ───────────────────────────────────────────────────────────────────

def insert_quake(
    event_id: str,
    occurred_at: str | None,
    hypocenter: str | None,
    magnitude: float | None,
    max_scale: int | None,
    tsunami: str | None,
    raw_json: dict | None,
    db_path: str | None = None,
) -> bool:
    """地震情報を挿入する。重複は無視。挿入できた場合True。"""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO quakes
            (event_id, occurred_at, hypocenter, magnitude, max_scale, tsunami, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                occurred_at,
                hypocenter,
                magnitude,
                max_scale,
                tsunami,
                json.dumps(raw_json, ensure_ascii=False) if raw_json else None,
            ),
        )
        return cur.rowcount > 0


def get_recent_quakes(limit: int = 20, min_scale: int = 0, db_path: str | None = None) -> list[dict]:
    """最新地震情報をlimit件返す。min_scale以上のみ。"""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM quakes
            WHERE max_scale >= ?
            ORDER BY occurred_at DESC
            LIMIT ?
            """,
            (min_scale, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# ─── warnings ─────────────────────────────────────────────────────────────────

def upsert_warning(
    area_code: str,
    area_name: str | None,
    warning_type: str,
    level: str,
    reported_at: str | None,
    db_path: str | None = None,
) -> None:
    """警報・注意報をupsertする。"""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO warnings (area_code, area_name, warning_type, level, reported_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(area_code, warning_type)
            DO UPDATE SET area_name=excluded.area_name, level=excluded.level,
                          reported_at=excluded.reported_at, fetched_at=datetime('now','localtime')
            """,
            (area_code, area_name, warning_type, level, reported_at),
        )


def delete_warnings_by_pref(pref_code: str, db_path: str | None = None) -> None:
    """指定都道府県コードに紐づく警報を全削除する（最新化前の掃除用）。"""
    with get_conn(db_path) as conn:
        conn.execute(
            "DELETE FROM warnings WHERE area_code LIKE ?",
            (f"{pref_code}%",),
        )


def delete_warnings_by_type(warning_type: str, db_path: str | None = None) -> None:
    """指定警報種別の警報を全削除する（土砂災害警戒情報等の一括リフレッシュ用）。"""
    with get_conn(db_path) as conn:
        conn.execute(
            "DELETE FROM warnings WHERE warning_type = ?",
            (warning_type,),
        )


def get_active_warnings(db_path: str | None = None) -> list[dict]:
    """現在の警報・注意報一覧を返す。"""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM warnings ORDER BY level DESC, area_code ASC"
        ).fetchall()
        return [dict(r) for r in rows]


# ─── typhoons ─────────────────────────────────────────────────────────────────

def upsert_typhoon(
    typhoon_id: str,
    name: str | None,
    status: str | None,
    raw_json: dict | None,
    reported_at: str | None = None,
    db_path: str | None = None,
) -> None:
    """台風情報をupsertする。"""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO typhoons (typhoon_id, name, status, reported_at, raw_json)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(typhoon_id)
            DO UPDATE SET name=excluded.name, status=excluded.status,
                          reported_at=COALESCE(excluded.reported_at, typhoons.reported_at),
                          raw_json=excluded.raw_json, fetched_at=datetime('now','localtime')
            WHERE excluded.reported_at IS NULL
               OR typhoons.reported_at IS NULL
               OR excluded.reported_at >= typhoons.reported_at
            """,
            (
                typhoon_id,
                name,
                status,
                reported_at,
                json.dumps(raw_json, ensure_ascii=False) if raw_json is not None else None,
            ),
        )


def get_active_typhoons(db_path: str | None = None) -> list[dict]:
    """現在の台風情報一覧を返す。"""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM typhoons ORDER BY fetched_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ─── heatstroke_alerts ────────────────────────────────────────────────────────

def upsert_heatstroke_alert(
    area_name: str,
    target_date: str,
    level: str,
    reported_at: str | None,
    db_path: str | None = None,
) -> None:
    """熱中症警戒アラートをupsertする。"""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO heatstroke_alerts (area_name, target_date, level, reported_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(area_name, target_date)
            DO UPDATE SET level=excluded.level, reported_at=excluded.reported_at,
                          fetched_at=datetime('now','localtime')
            """,
            (area_name, target_date, level, reported_at),
        )


def delete_past_heatstroke_alerts(db_path: str | None = None) -> int:
    """target_date が今日より前の熱中症警戒アラートを削除する。削除件数を返す。"""
    with get_conn(db_path) as conn:
        cursor = conn.execute(
            "DELETE FROM heatstroke_alerts WHERE target_date < date('now', 'localtime')"
        )
        return cursor.rowcount


def get_heatstroke_alerts(db_path: str | None = None) -> list[dict]:
    """熱中症警戒アラート一覧を返す。取得前に過去日付データを削除する。"""
    delete_past_heatstroke_alerts(db_path)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM heatstroke_alerts ORDER BY target_date DESC, area_name ASC"
        ).fetchall()
        return [dict(r) for r in rows]


# ─── volcano_alerts ───────────────────────────────────────────────────────────

def upsert_volcano_alert(
    volcano_name: str,
    alert_level: int | None,
    alert_type: str,
    description: str | None,
    reported_at: str | None,
    db_path: str | None = None,
) -> None:
    """噴火警報をupsertする。"""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO volcano_alerts (volcano_name, alert_level, alert_type, description, reported_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(volcano_name, alert_type)
            DO UPDATE SET alert_level=excluded.alert_level, description=excluded.description,
                          reported_at=excluded.reported_at, fetched_at=datetime('now','localtime')
            """,
            (volcano_name, alert_level, alert_type, description, reported_at),
        )


def get_volcano_alerts(db_path: str | None = None) -> list[dict]:
    """噴火警報一覧を返す。"""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM volcano_alerts ORDER BY alert_level DESC, reported_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ─── flood_forecasts ──────────────────────────────────────────────────────────

def upsert_flood_forecast(
    river_name: str,
    area_name: str | None,
    level: str,
    reported_at: str | None,
    db_path: str | None = None,
) -> None:
    """河川洪水予報をupsertする。"""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO flood_forecasts (river_name, area_name, level, reported_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(river_name, level)
            DO UPDATE SET area_name=excluded.area_name, reported_at=excluded.reported_at,
                          fetched_at=datetime('now','localtime')
            """,
            (river_name, area_name, level, reported_at),
        )


def get_flood_forecasts(db_path: str | None = None) -> list[dict]:
    """洪水予報一覧を返す。"""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM flood_forecasts ORDER BY reported_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ─── environment_info ─────────────────────────────────────────────────────────

def upsert_environment_info(
    info_type: str,
    area_name: str | None,
    level: str | None,
    description: str | None,
    valid_from: str | None,
    valid_to: str | None,
    db_path: str | None = None,
) -> None:
    """環境情報（黄砂・紫外線）をupsertする。"""
    with get_conn(db_path) as conn:
        conn.execute(
            """
            INSERT INTO environment_info (info_type, area_name, level, description, valid_from, valid_to)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(info_type, area_name, valid_from)
            DO UPDATE SET level=excluded.level, description=excluded.description,
                          valid_to=excluded.valid_to, fetched_at=datetime('now','localtime')
            """,
            (info_type, area_name, level, description, valid_from, valid_to),
        )


def get_environment_info(db_path: str | None = None) -> list[dict]:
    """環境情報一覧を返す。"""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM environment_info ORDER BY info_type, valid_from DESC"
        ).fetchall()
        return [dict(r) for r in rows]


# ─── xml_feed_state ───────────────────────────────────────────────────────────

def is_processed(entry_id: str, db_path=None) -> bool:
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT 1 FROM xml_feed_state WHERE entry_id=?", (entry_id,)).fetchone()
        return row is not None


def mark_processed(entry_id: str, db_path=None) -> None:
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO xml_feed_state (entry_id) VALUES (?)",
            (entry_id,),
        )


def cleanup_xml_feed_state(db_path: str | None = None) -> int:
    """14日以上前に処理済みのxml_feed_stateエントリを削除する。削除件数を返す。"""
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "DELETE FROM xml_feed_state WHERE processed_at < datetime('now', '-14 days', 'localtime')"
        )
        return cur.rowcount


# ─── collection_log ───────────────────────────────────────────────────────────

def insert_collection_log(
    source: str,
    status: str,
    item_count: int = 0,
    message: str | None = None,
    db_path: str | None = None,
) -> None:
    """収集ログを追記する。"""
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO collection_log (source, status, item_count, message) VALUES (?, ?, ?, ?)",
            (source, status, item_count, message),
        )


def get_latest_collection_log(db_path: str | None = None) -> list[dict]:
    """各sourceの最新ログを返す。"""
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM collection_log cl
            WHERE ran_at = (SELECT MAX(ran_at) FROM collection_log WHERE source = cl.source)
            ORDER BY source ASC
            """,
        ).fetchall()
        return [dict(r) for r in rows]
