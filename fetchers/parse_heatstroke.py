"""VPFT50 熱中症警戒アラート パーサー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import upsert_heatstroke_alert
from fetchers.xml_utils import find_text

logger = logging.getLogger(__name__)


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VPFT50 XMLを解析して熱中症警戒アラートをDBに保存する。保存件数を返す。"""
    # target_date は Head か Body どちらにあるかを試みる
    target_date = find_text(root, "Head/TargetDateTime") or find_text(root, "Body/Warning/Item/TargetDateTime") or ""

    saved = 0
    for item in root.findall(".//Warning/Item"):
        kind_el = item.find("Kind")
        if kind_el is None:
            continue

        level = (kind_el.findtext("Name") or "").strip()
        status = (kind_el.findtext("Status") or "").strip()

        if status != "発表":
            continue

        # Item 内に TargetDateTime があれば上書き
        item_target = item.findtext("TargetDateTime")
        effective_date = (item_target or target_date).strip()

        areas_el = item.find("Areas")
        if areas_el is None:
            # エリアなしでも1件として保存
            if level:
                upsert_heatstroke_alert(
                    area_name="",
                    target_date=effective_date,
                    level=level,
                    reported_at=reported_at,
                    db_path=db_path,
                )
                saved += 1
            continue

        for area_el in areas_el.findall("Area"):
            area_name = (area_el.findtext("Name") or "").strip()
            upsert_heatstroke_alert(
                area_name=area_name,
                target_date=effective_date,
                level=level,
                reported_at=reported_at,
                db_path=db_path,
            )
            saved += 1

    logger.info("熱中症警戒アラート保存: %d件", saved)
    return saved
