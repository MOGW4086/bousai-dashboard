"""全フェッチャーを順次実行し収集ログに記録するスケジューラー。"""
import argparse
import logging
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Config
from db.init_db import init_db
from db.models import (
    cleanup_xml_feed_state,
    delete_defunct_typhoons,
    delete_past_heatstroke_alerts,
    insert_collection_log,
)

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


def _run_cleanup_task(task_func: Callable[[str | None], int], task_name: str, success_log_msg: str, db_path: str | None) -> None:
    """クリーンアップタスクを実行し、例外が発生してもスキップして警告ログを出す。"""
    try:
        deleted_count = task_func(db_path)
        logger.info(success_log_msg, deleted_count)
    except Exception as e:
        logger.warning("%s クリーンアップ失敗（スキップ）: %s", task_name, e, exc_info=True)


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

    _run_cleanup_task(
        cleanup_xml_feed_state,
        "xml_feed_state",
        "xml_feed_state クリーンアップ: %d件削除（14日以上前）",
        path
    )
    _run_cleanup_task(
        delete_past_heatstroke_alerts,
        "heatstroke_alerts",
        "heatstroke_alerts クリーンアップ: %d件削除（過去日付）",
        path
    )
    _run_cleanup_task(
        delete_defunct_typhoons,
        "typhoons(defunct)",
        "消滅台風クリーンアップ: %d件削除",
        path
    )


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
