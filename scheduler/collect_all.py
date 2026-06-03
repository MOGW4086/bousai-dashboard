"""全フェッチャーを順次実行し収集ログに記録するスケジューラー。"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Config
from db.init_db import init_db
from db.models import insert_collection_log

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

SOURCES = ["atom", "air"]


def run_fetcher(source: str, db_path: str) -> tuple[str, int, str | None]:
    """指定ソースのフェッチャーを実行する。(status, item_count, message) を返す。"""
    try:
        module = __import__(f"fetchers.{source}", fromlist=[source])
        count = module.fetch(db_path=db_path)
        return "ok", count, None
    except Exception as e:
        logger.error("フェッチャーエラー [%s]: %s", source, e)
        return "error", 0, str(e)


def collect(sources: list[str], db_path: str | None = None) -> None:
    """指定ソース一覧のデータを収集する。"""
    path = db_path or Config.DB_PATH
    init_db(path)

    logger.info("データ収集開始: %s", sources)
    for source in sources:
        logger.info("[%s] 収集開始...", source)
        status, count, msg = run_fetcher(source, path)
        insert_collection_log(
            source=source,
            status=status,
            item_count=count,
            message=msg,
            db_path=path,
        )
        if status == "ok":
            logger.info("[%s] 完了: %d件", source, count)
        else:
            logger.error("[%s] 失敗: %s", source, msg)

    logger.info("データ収集完了")


def main() -> None:
    """CLIエントリポイント。--source で単一種別実行可能。"""
    parser = argparse.ArgumentParser(description="防災情報データ収集")
    parser.add_argument(
        "--source",
        choices=SOURCES + ["quake", "warning", "heatstroke", "typhoon", "volcano", "river", "environment"],
        help="収集するデータソース（省略時は全て）",
    )
    args = parser.parse_args()

    targets = [args.source] if args.source else SOURCES
    collect(targets)


if __name__ == "__main__":
    main()
