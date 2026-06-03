"""VPWW53 気象警報・注意報 パーサー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import upsert_warning, delete_warnings_by_pref
from fetchers.xml_utils import find_text

logger = logging.getLogger(__name__)


def _level(warning_type: str) -> str:
    if "特別警報" in warning_type:
        return "special_warning"
    if "警報" in warning_type:
        return "warning"
    return "advisory"


def _pref_code(area_code: str) -> str:
    """area_code の先頭3桁 + "000" を返す。"""
    return area_code[:3] + "000"


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VPWW53 XMLを解析して警報・注意報をDBに保存する。保存件数を返す。"""
    # 気象警報・注意報（一次細分区域等）ブロックを探す
    warning_block = None
    for w in root.findall(".//Warning"):
        wtype = w.get("type", "")
        if "気象警報・注意報" in wtype and "一次細分区域" in wtype:
            warning_block = w
            break

    if warning_block is None:
        # フォールバック: 最初の Warning ブロック
        warning_block = root.find(".//Warning")

    if warning_block is None:
        logger.debug("Warning ブロックが見つかりませんでした")
        return 0

    # 処理対象 pref_code を収集してから一括削除
    deleted_prefs: set[str] = set()
    saved = 0

    for item in warning_block.findall("Item"):
        area_el = item.find("Area")
        if area_el is None:
            continue
        area_name = (area_el.findtext("Name") or "").strip()
        area_code = (area_el.findtext("Code") or "").strip()

        for kind in item.findall("Kind"):
            kind_name = (kind.findtext("Name") or "").strip()
            status = (kind.findtext("Status") or "").strip()

            if status not in ("発表", "継続"):
                continue

            if area_code:
                pref = _pref_code(area_code)
                if pref not in deleted_prefs:
                    delete_warnings_by_pref(pref, db_path=db_path)
                    deleted_prefs.add(pref)

            level = _level(kind_name)
            upsert_warning(
                area_code=area_code,
                area_name=area_name,
                warning_type=kind_name,
                level=level,
                reported_at=reported_at,
                db_path=db_path,
            )
            saved += 1

    logger.info("警報保存: %d件", saved)
    return saved
