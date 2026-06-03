"""黄砂・紫外線情報フェッチャー（スケルトン実装）。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetchers.base import http_get_json
from db.models import upsert_environment_info

logger = logging.getLogger(__name__)

JMA_INFO_URL = "https://www.jma.go.jp/bosai/information/data/information.json"

ENV_KEYWORDS = {
    "kosa": ["黄砂"],
    "uv": ["紫外線"],
}


def fetch(db_path: str | None = None) -> int:
    """気象庁情報一覧から黄砂・紫外線情報を取得・保存する（スケルトン）。"""
    info_list = http_get_json(JMA_INFO_URL)
    if info_list is None:
        logger.error("気象庁情報一覧の取得に失敗しました")
        return 0

    if not isinstance(info_list, list):
        return 0

    total = 0
    for item in info_list:
        title = item.get("title", "") + item.get("type", "")
        info_type = None
        for key, keywords in ENV_KEYWORDS.items():
            if any(kw in title for kw in keywords):
                info_type = key
                break

        if info_type is None:
            continue

        # TODO: 詳細パース実装（後続フェーズ）
        upsert_environment_info(
            info_type=info_type,
            area_name=item.get("area", "全国"),
            level=None,
            description=title,
            valid_from=item.get("pubDate") or item.get("reportDatetime"),
            valid_to=None,
            db_path=db_path,
        )
        total += 1

    logger.info("環境情報: %d件保存（スケルトン）", total)
    return total
