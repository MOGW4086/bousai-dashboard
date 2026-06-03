"""P2P地震情報v2 APIから地震・津波情報を取得するフェッチャー。"""
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetchers.base import http_get_json
from db.models import insert_quake

logger = logging.getLogger(__name__)

API_URL = "https://api.p2pquake.net/v2/jma/quake?limit=20"
CODE_QUAKE = 551  # 地震情報


def fetch(db_path: str | None = None) -> int:
    """P2P地震情報APIから地震情報を取得し保存する。保存件数を返す。"""
    data = http_get_json(API_URL)
    if data is None:
        logger.error("地震情報の取得に失敗しました")
        return 0

    if not isinstance(data, list):
        logger.error("予期しないレスポンス形式: %s", type(data))
        return 0

    saved = 0
    for item in data:
        if item.get("code") != CODE_QUAKE:
            continue

        event_id = item.get("id") or item.get("_id") or str(item.get("time", ""))
        if not event_id:
            continue

        eq = item.get("earthquake", {})
        hypocenter_obj = eq.get("hypocenter", {})
        hypocenter = hypocenter_obj.get("name")
        magnitude = eq.get("magnitude")
        max_scale = eq.get("maxScale")
        occurred_at = eq.get("time")
        tsunami = item.get("issue", {}).get("type")

        if insert_quake(
            event_id=str(event_id),
            occurred_at=occurred_at,
            hypocenter=hypocenter,
            magnitude=magnitude,
            max_scale=max_scale,
            tsunami=tsunami,
            raw_json=item,
            db_path=db_path,
        ):
            saved += 1

    logger.info("地震情報: %d件保存", saved)
    return saved
