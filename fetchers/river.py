"""河川洪水予報フェッチャー（スケルトン実装）。XMLパースは後続フェーズで実装。"""
import logging

logger = logging.getLogger(__name__)


def fetch(db_path: str | None = None) -> int:
    """河川洪水予報を取得する（スケルトン）。常に0を返す。"""
    logger.info("河川洪水予報フェッチャーはスケルトン実装です（後続フェーズで実装予定）")
    return 0
