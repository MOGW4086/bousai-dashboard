"""VXWW50 土砂災害警戒情報 パーサー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import upsert_warning

logger = logging.getLogger(__name__)

SEDIMENT_TYPE = "土砂災害警戒情報"


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VXWW50 XMLを解析して土砂災害警戒情報をDBに保存する。保存件数を返す。"""
    saved = 0

    # Warning ブロックを全検索
    for warning_block in root.findall(".//Warning"):
        for item in warning_block.findall("Item"):
            area_el = item.find("Area")
            if area_el is None:
                continue
            area_name = (area_el.findtext("Name") or "").strip()
            area_code = (area_el.findtext("Code") or "").strip()

            for kind in item.findall("Kind"):
                kind_name = (kind.findtext("Name") or "").strip()
                status = (kind.findtext("Status") or "").strip()

                if kind_name != SEDIMENT_TYPE:
                    continue
                if status not in ("警戒", "発表"):
                    continue

                upsert_warning(
                    area_code=area_code,
                    area_name=area_name,
                    warning_type=SEDIMENT_TYPE,
                    level="special_warning",
                    reported_at=reported_at,
                    db_path=db_path,
                )
                saved += 1

    logger.info("土砂災害警戒情報保存: %d件", saved)
    return saved
