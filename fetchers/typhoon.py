"""気象庁台風情報JSONを取得するフェッチャー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetchers.base import http_get_json
from db.models import upsert_typhoon

logger = logging.getLogger(__name__)

JMA_INFO_URL = "https://www.jma.go.jp/bosai/information/data/information.json"

# 台風情報に関連するコード種別
TYPHOON_TITLES = ["台風情報", "台風の発生情報"]


def fetch(db_path: str | None = None) -> int:
    """気象庁情報一覧から台風情報を抽出・保存する。保存件数を返す。"""
    data = http_get_json(JMA_INFO_URL)
    if data is None:
        logger.error("気象庁情報一覧の取得に失敗しました")
        return 0

    if not isinstance(data, list):
        logger.error("予期しないレスポンス形式: %s", type(data))
        return 0

    saved = 0
    for item in data:
        title = item.get("title", "")
        if not any(t in title for t in TYPHOON_TITLES):
            continue

        typhoon_id = item.get("id") or item.get("url", "").split("/")[-1]
        if not typhoon_id:
            continue

        name = item.get("name") or title
        status = item.get("status") or item.get("type", "")

        upsert_typhoon(
            typhoon_id=str(typhoon_id),
            name=name,
            status=status,
            raw_json=item,
            db_path=db_path,
        )
        saved += 1

    logger.info("台風情報: %d件保存", saved)
    return saved
