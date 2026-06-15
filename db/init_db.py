"""データベース初期化スクリプト。テーブルが存在しない場合のみ作成する。"""
import sqlite3
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import Config


DDL = """
-- デバイス別地域設定（UUID Cookieでデバイス識別）
CREATE TABLE IF NOT EXISTS viewer_areas (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    viewer_id   TEXT NOT NULL,
    pref_code   TEXT NOT NULL,
    area_code   TEXT NOT NULL,
    name        TEXT NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(viewer_id, area_code)
);

-- 地震・津波情報
CREATE TABLE IF NOT EXISTS quakes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL UNIQUE,
    occurred_at TEXT,
    hypocenter  TEXT,
    magnitude   REAL,
    max_scale   INTEGER,
    tsunami     TEXT,
    raw_json    TEXT,
    latitude    REAL,
    longitude   REAL,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 気象警報・注意報（土砂・大雪・高潮含む）
CREATE TABLE IF NOT EXISTS warnings (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    area_code    TEXT NOT NULL,
    area_name    TEXT,
    warning_type TEXT NOT NULL,
    level        TEXT NOT NULL DEFAULT 'warning',
    reported_at  TEXT,
    fetched_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(area_code, warning_type)
);

-- 台風情報
CREATE TABLE IF NOT EXISTS typhoons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    typhoon_id  TEXT NOT NULL UNIQUE,
    name        TEXT,
    status      TEXT,
    reported_at TEXT,
    raw_json    TEXT,
    latitude    REAL,
    longitude   REAL,
    track_json  TEXT,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- 熱中症警戒アラート
CREATE TABLE IF NOT EXISTS heatstroke_alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    area_name   TEXT NOT NULL,
    target_date TEXT NOT NULL,
    level       TEXT NOT NULL,
    reported_at TEXT,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(area_name, target_date)
);

-- 噴火警報・火山灰情報
CREATE TABLE IF NOT EXISTS volcano_alerts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    volcano_name TEXT NOT NULL,
    alert_level  INTEGER,
    alert_type   TEXT NOT NULL,
    description  TEXT,
    reported_at  TEXT,
    fetched_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(volcano_name, alert_type)
);

-- 河川洪水予報
CREATE TABLE IF NOT EXISTS flood_forecasts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    river_name  TEXT NOT NULL,
    area_name   TEXT,
    level       TEXT NOT NULL,
    reported_at TEXT,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(river_name, level)
);

-- 黄砂・紫外線等（環境情報）
CREATE TABLE IF NOT EXISTS environment_info (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    info_type   TEXT NOT NULL,
    area_name   TEXT,
    level       TEXT,
    description TEXT,
    valid_from  TEXT,
    valid_to    TEXT,
    fetched_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(info_type, area_name, valid_from)
);

-- 津波警報・注意報
CREATE TABLE IF NOT EXISTS tsunami_warnings (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    area_code     TEXT NOT NULL,
    area_name     TEXT,
    category      TEXT NOT NULL DEFAULT '',
    telegram_type TEXT NOT NULL DEFAULT '',
    reported_at   TEXT,
    fetched_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(area_code, telegram_type)
);

-- 収集ログ
CREATE TABLE IF NOT EXISTS collection_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    status      TEXT NOT NULL,
    item_count  INTEGER DEFAULT 0,
    message     TEXT,
    ran_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- JMA XMLフィード処理済みエントリ管理
CREATE TABLE IF NOT EXISTS xml_feed_state (
    entry_id     TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_xml_feed_state_processed_at ON xml_feed_state(processed_at);
"""


def init_db(db_path: str | None = None) -> None:
    """データベースを初期化する。テーブルが未作成の場合のみ作成。"""
    path = db_path or Config.DB_PATH
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(DDL)
        conn.commit()
        # PRAGMA table_info でカラム存在確認してから ALTER TABLE（OperationalError の隠蔽を防ぐ）
        columns = [row[1] for row in conn.execute("PRAGMA table_info(typhoons)").fetchall()]
        if "reported_at" not in columns:
            conn.execute("ALTER TABLE typhoons ADD COLUMN reported_at TEXT")
            conn.commit()
        # tsunami_warnings に telegram_type カラムを追加（既存DBのマイグレーション）
        tw_cols = [row[1] for row in conn.execute("PRAGMA table_info(tsunami_warnings)").fetchall()]
        if "telegram_type" not in tw_cols:
            conn.execute("ALTER TABLE tsunami_warnings ADD COLUMN telegram_type TEXT NOT NULL DEFAULT ''")
            conn.commit()
        # quakes に latitude/longitude カラムを追加（既存DBのマイグレーション）
        q_cols = [row[1] for row in conn.execute("PRAGMA table_info(quakes)").fetchall()]
        if "latitude" not in q_cols:
            conn.execute("ALTER TABLE quakes ADD COLUMN latitude REAL")
        if "longitude" not in q_cols:
            conn.execute("ALTER TABLE quakes ADD COLUMN longitude REAL")
        conn.commit()
        # typhoons に latitude/longitude/track_json カラムを追加（既存DBのマイグレーション）
        ty_cols = [row[1] for row in conn.execute("PRAGMA table_info(typhoons)").fetchall()]
        if "latitude" not in ty_cols:
            conn.execute("ALTER TABLE typhoons ADD COLUMN latitude REAL")
        if "longitude" not in ty_cols:
            conn.execute("ALTER TABLE typhoons ADD COLUMN longitude REAL")
        if "track_json" not in ty_cols:
            conn.execute("ALTER TABLE typhoons ADD COLUMN track_json TEXT")
        conn.commit()
        print(f"[init_db] DB初期化完了: {path}")
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
