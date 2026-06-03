"""そらまめ君（大気汚染）フェッチャー（Phase2・スケルトン実装）。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import Config

logger = logging.getLogger(__name__)


def fetch(db_path: str | None = None) -> int:
    """そらまめ君からデータを取得する（Phase2）。APIキー未設定なら即座にスキップ。"""
    if not Config.SORAMAME_API_KEY:
        logger.info("そらまめ君APIキー未設定のためスキップ（Phase2で実装予定）")
        return 0

    # TODO: APIキー設定後に実装（Phase2）
    logger.info("そらまめ君フェッチャーはPhase2で実装予定です")
    return 0
