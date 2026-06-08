"""マイグレーション 002: tsunami_warnings テーブルに telegram_type カラムを追加し
UNIQUE 制約を (area_code, telegram_type) に変更する。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from db.models import get_conn

MIGRATION_NAME = "migration_002"


def run(db_path=None):
    with get_conn(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applied_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)
        if conn.execute("SELECT 1 FROM applied_migrations WHERE name=?", (MIGRATION_NAME,)).fetchone():
            print(f"[{MIGRATION_NAME}] 既に適用済みです")
            return

        # テーブル再作成（UNIQUE制約変更）
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tsunami_warnings_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                area_code     TEXT NOT NULL,
                area_name     TEXT,
                category      TEXT NOT NULL DEFAULT '',
                telegram_type TEXT NOT NULL DEFAULT '',
                reported_at   TEXT,
                fetched_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                UNIQUE(area_code, telegram_type)
            );
            INSERT INTO tsunami_warnings_new
                (id, area_code, area_name, category, telegram_type, reported_at, fetched_at)
            SELECT id, area_code, area_name, category, '', reported_at, fetched_at
            FROM tsunami_warnings;
            DROP TABLE tsunami_warnings;
            ALTER TABLE tsunami_warnings_new RENAME TO tsunami_warnings;
        """)
        # 移行前データは telegram_type='' で不完全なため削除し、次回収集で再取得させる
        conn.execute("DELETE FROM tsunami_warnings WHERE telegram_type = ''")
        # VTSE41 の処理済みフラグをリセット（telegram_type付きで再収集させる）
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='xml_feed_state'"
        ).fetchone()
        if exists:
            conn.execute("DELETE FROM xml_feed_state WHERE entry_id LIKE '%VTSE41%'")
        conn.execute("INSERT INTO applied_migrations (name) VALUES (?)", (MIGRATION_NAME,))
    print(f"[{MIGRATION_NAME}] 適用完了: tsunami_warnings に telegram_type カラム追加・UNIQUE制約変更")


if __name__ == "__main__":
    run()
