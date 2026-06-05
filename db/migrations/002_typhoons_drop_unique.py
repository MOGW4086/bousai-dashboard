"""
マイグレーション 002: typhoons テーブルの UNIQUE(typhoon_id) 制約を削除

typhoons テーブルを ON CONFLICT upsert 方式から全削除→再挿入方式へ変更するため、
UNIQUE 制約が不要になった。SQLite では制約の直接削除ができないため、
テーブルを再作成して既存データを移行する。
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from config import Config

MIGRATION_NAME = "migration_002"


def run(db_path: str | None = None) -> None:
    """typhoons テーブルの UNIQUE(typhoon_id) 制約を除去する。"""
    path = db_path or Config.DB_PATH
    conn = sqlite3.connect(path)
    conn.isolation_level = None  # autocommit モード: 途中 return 時の暗黙的トランザクション回避
    try:
        # applied_migrations テーブルを作成（なければ）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applied_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)

        # 冪等性チェック: 既に適用済みなら終了
        already = conn.execute(
            "SELECT 1 FROM applied_migrations WHERE name = ?", (MIGRATION_NAME,)
        ).fetchone()
        if already:
            print(f"[{MIGRATION_NAME}] 既に適用済みです")
            return

        # UNIQUE 制約の有無を確認（sqlite_master でテーブルの DDL を確認、コメント行は除外）
        table_sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='typhoons'"
        ).fetchone()

        sql_clean = ""
        if table_sql and table_sql[0]:
            sql_clean = "\n".join(
                line for line in table_sql[0].splitlines() if not line.strip().startswith("--")
            )

        if table_sql is None or "UNIQUE" not in sql_clean.upper():
            # 新規インストール時など: 制約が最初から存在しないケース
            # applied_migrations に記録しておくことで次回の applied チェックで早期終了できる
            print(f"[{MIGRATION_NAME}] UNIQUE 制約は既に存在しません（スキップ）")
            conn.execute("INSERT INTO applied_migrations (name) VALUES (?)", (MIGRATION_NAME,))
            return

        before_count = conn.execute("SELECT COUNT(*) FROM typhoons").fetchone()[0]

        # テーブル再作成で UNIQUE 制約を除去
        conn.execute("BEGIN")
        try:
            conn.execute("""
                CREATE TABLE typhoons_new (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    typhoon_id  TEXT NOT NULL,
                    name        TEXT,
                    status      TEXT,
                    reported_at TEXT,
                    raw_json    TEXT,
                    fetched_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                )
            """)
            conn.execute("""
                INSERT INTO typhoons_new (id, typhoon_id, name, status, reported_at, raw_json, fetched_at)
                SELECT id, typhoon_id, name, status, reported_at, raw_json, fetched_at FROM typhoons
            """)
            conn.execute("DROP TABLE typhoons")
            conn.execute("ALTER TABLE typhoons_new RENAME TO typhoons")
            conn.execute("INSERT INTO applied_migrations (name) VALUES (?)", (MIGRATION_NAME,))
            conn.execute("COMMIT")
        except Exception as e:
            conn.execute("ROLLBACK")
            raise e

        after_count = conn.execute("SELECT COUNT(*) FROM typhoons").fetchone()[0]
        print(f"[002] typhoons: UNIQUE 制約を削除（レコード数: {before_count} → {after_count}）")

    finally:
        conn.close()


if __name__ == "__main__":
    run()
