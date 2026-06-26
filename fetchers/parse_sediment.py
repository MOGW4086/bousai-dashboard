"""VXWW50 土砂災害警戒情報 パーサー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import upsert_warning, delete_warnings_by_pref_and_type
from scheduler.area_master import get_pref_code_from_area_code

logger = logging.getLogger(__name__)

SEDIMENT_TYPE = "土砂災害警戒情報"


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VXWW50 XMLを解析して土砂災害警戒情報をDBに保存する。保存件数を返す。"""
    saved = 0
    deleted_prefs: set[str] = set()

    # Warning ブロックを全検索
    for warning_block in root.findall(".//Warning"):
        for item in warning_block.findall("Item"):
            area_el = item.find("Area")
            if area_el is None:
                continue
            area_name = (area_el.findtext("Name") or "").strip()
            area_code = (area_el.findtext("Code") or "").strip()

            # 初出の都道府県は旧データを削除する（VXWW50は一県全域を網羅するため）
            if area_code:
                pref = get_pref_code_from_area_code(area_code)
                if pref and pref not in deleted_prefs:
                    delete_warnings_by_pref_and_type(pref, SEDIMENT_TYPE, db_path=db_path)
                    deleted_prefs.add(pref)

            for kind in item.findall("Kind"):
                # VXWW50では Kind>Name が "警戒" = 警戒情報発令中、"なし" = 対象外
                kind_name = (kind.findtext("Name") or "").strip()
                if kind_name != "警戒":
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
