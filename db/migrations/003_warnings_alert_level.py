"""マイグレーション 003: warnings テーブルに alert_level カラムを追加する。

気象庁 R06 形式電文（VPWW55〜61）が警戒レベル情報を含むため、
warnings テーブルに alert_level INTEGER 列を追加する。
既存レコード（VPWW53 由来）は NULL のまま保持し、
フロントエンドはレベルなしとして扱う。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from db.models import get_conn

MIGRATION_NAME = "migration_003"


def run(db_path: str | None = None) -> None:
    """migration_003 を適用する。冪等（2回実行しても安全）。"""
    with get_conn(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS applied_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
            )
        """)
        if conn.execute(
            "SELECT 1 FROM applied_migrations WHERE name = ?", (MIGRATION_NAME,)
        ).fetchone():
            print(f"[{MIGRATION_NAME}] 既に適用済みです")
            return

        cols = [row[1] for row in conn.execute("PRAGMA table_info(warnings)").fetchall()]
        if "alert_level" not in cols:
            conn.execute("ALTER TABLE warnings ADD COLUMN alert_level INTEGER")
            print(f"[{MIGRATION_NAME}] warnings.alert_level カラム追加完了")
        else:
            print(f"[{MIGRATION_NAME}] alert_level カラムは既に存在します（スキップ）")

        conn.execute("INSERT INTO applied_migrations (name) VALUES (?)", (MIGRATION_NAME,))
    print(f"[{MIGRATION_NAME}] 適用完了")


if __name__ == "__main__":
    run()
