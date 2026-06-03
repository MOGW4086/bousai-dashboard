"""噴火警報・火山灰情報を取得するフェッチャー（スケルトン実装）。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetchers.base import http_get_json, http_get_xml
from db.models import upsert_volcano_alert

logger = logging.getLogger(__name__)

JMA_INFO_URL = "https://www.jma.go.jp/bosai/information/data/information.json"

VOLCANO_TITLE_KEYWORDS = ["噴火警報", "火山灰", "噴火速報", "火口周辺警報"]


def fetch(db_path: str | None = None) -> int:
    """気象庁情報一覧から噴火警報電文URLを探して保存する（スケルトン）。"""
    info_list = http_get_json(JMA_INFO_URL)
    if info_list is None:
        logger.error("気象庁情報一覧の取得に失敗しました")
        return 0

    if not isinstance(info_list, list):
        return 0

    total = 0
    for item in info_list:
        title = item.get("title", "") + item.get("type", "")
        if not any(kw in title for kw in VOLCANO_TITLE_KEYWORDS):
            continue

        url = item.get("url") or item.get("link")
        if not url:
            continue

        reported_at = item.get("pubDate") or item.get("reportDatetime")

        # TODO: XMLパース実装（後続フェーズ）
        # root = http_get_xml(url)
        # if root is None:
        #     continue
        # volcano_name, alert_level = _parse_volcano_xml(root)

        # スケルトン：タイトルから仮登録
        alert_type = "eruption_warning" if "噴火警報" in title else "ash"
        upsert_volcano_alert(
            volcano_name=item.get("name", "不明"),
            alert_level=None,
            alert_type=alert_type,
            description=title,
            reported_at=reported_at,
            db_path=db_path,
        )
        total += 1

    logger.info("噴火警報: %d件保存（スケルトン）", total)
    return total
