"""熱中症警戒アラート（気象庁XML VPFT50）を取得するフェッチャー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetchers.base import http_get_json, http_get_xml
from db.models import upsert_heatstroke_alert

logger = logging.getLogger(__name__)

JMA_INFO_URL = "https://www.jma.go.jp/bosai/information/data/information.json"

# 熱中症警戒アラートの電文種別コード
HEATSTROKE_TITLE_KEYWORDS = ["熱中症", "VPFT50"]

# lxml 名前空間
NS = {
    "jmx": "http://xml.kishou.go.jp/jmaxml1/",
    "eb": "http://xml.kishou.go.jp/jmaxml1/elementBasis1/",
    "jmx_ib": "http://xml.kishou.go.jp/jmaxml1/informationBasis1/",
}


def _parse_heatstroke_xml(root, reported_at: str | None, db_path: str | None) -> int:
    """熱中症警戒アラートXMLをパースしてDBに保存する。保存件数を返す。"""
    saved = 0
    try:
        # 地域名・対象日・レベルを抽出（名前空間はフォールバック込みで探索）
        bodies = root.findall(".//{*}Body") or root.findall("Body")
        for body in bodies:
            areas = body.findall(".//{*}Area") or body.findall(".//Area")
            for area in areas:
                area_name_el = area.find("{*}Name") or area.find("Name")
                level_el = area.find("{*}Kind/{*}Name") or area.find(".//Kind/Name")
                date_el = area.find("{*}ValidDateTime") or area.find(".//ValidDateTime")

                area_name = area_name_el.text if area_name_el is not None else "不明"
                level = level_el.text if level_el is not None else "警戒"
                target_date = date_el.text[:10] if date_el is not None and date_el.text else ""

                if not target_date:
                    continue

                upsert_heatstroke_alert(
                    area_name=area_name,
                    target_date=target_date,
                    level=level,
                    reported_at=reported_at,
                    db_path=db_path,
                )
                saved += 1
    except Exception as e:
        logger.error("熱中症XMLパースエラー: %s", e)
    return saved


def fetch(db_path: str | None = None) -> int:
    """気象庁情報一覧から熱中症警戒アラート電文URLを探してデータを保存する。"""
    info_list = http_get_json(JMA_INFO_URL)
    if info_list is None:
        logger.error("気象庁情報一覧の取得に失敗しました")
        return 0

    if not isinstance(info_list, list):
        return 0

    total = 0
    for item in info_list:
        title = item.get("title", "") + item.get("type", "")
        if not any(kw in title for kw in HEATSTROKE_TITLE_KEYWORDS):
            continue

        url = item.get("url") or item.get("link")
        if not url:
            continue

        reported_at = item.get("pubDate") or item.get("reportDatetime")
        root = http_get_xml(url)
        if root is None:
            logger.warning("熱中症XML取得失敗: %s", url)
            continue

        count = _parse_heatstroke_xml(root, reported_at, db_path)
        total += count

    logger.info("熱中症警戒アラート: %d件保存", total)
    return total
