"""
マイグレーション 001: 旧 bosai JSON データの削除

JMA XML フィード移行前の warning.py（bosai JSON）が挿入した
以下のレコードを削除する:
  - area_name が NULL または空文字のレコード（旧 warning.py は area_name=None で保存）
  - 7桁 area_code（旧 class20 形式: 1110000 等）のレコード

あわせて VPWW53 の xml_feed_state 処理済みフラグをリセットし、
次回 atom.fetch() で最新データを再取得できるようにする。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from db.models import get_conn

MIGRATION_NAME = "migration_001"


def run(db_path: str | None = None) -> None:
    with get_conn(db_path) as conn:
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
            print("既に適用済みです")
            return

        before = conn.execute("SELECT COUNT(*) FROM warnings").fetchone()[0]

        # 1. area_name が NULL または空のレコードを削除
        r1_count = conn.execute(
            "DELETE FROM warnings WHERE area_name IS NULL OR area_name = ''"
        ).rowcount

        # 2. 7桁 area_code（旧 class20 形式）のレコードを削除
        r2_count = conn.execute(
            "DELETE FROM warnings WHERE length(area_code) = 7"
        ).rowcount

        # 3. VPWW53 処理済みフラグをリセット（次回再取得させる）
        r3_count = conn.execute(
            "DELETE FROM xml_feed_state WHERE entry_id LIKE '%VPWW53%'"
        ).rowcount

        after = conn.execute("SELECT COUNT(*) FROM warnings").fetchone()[0]

        # マイグレーション適用を記録
        conn.execute(
            "INSERT INTO applied_migrations (name) VALUES (?)", (MIGRATION_NAME,)
        )

    print(f"[001] warnings: {before} → {after} 件")
    print(f"  area_name NULL 削除: {r1_count} 件")
    print(f"  7桁 area_code 削除: {r2_count} 件")
    print(f"  VPWW53 フラグリセット: {r3_count} 件")


if __name__ == "__main__":
    run()
