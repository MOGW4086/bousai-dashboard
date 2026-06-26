"""VXWW50 土砂災害警戒情報 パーサー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import save_sediment_warnings
from scheduler.area_master import get_pref_code_from_area_code

logger = logging.getLogger(__name__)

SEDIMENT_TYPE = "土砂災害警戒情報"


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VXWW50 XMLを解析して土砂災害警戒情報をDBに保存する。保存件数を返す。

    2パス構造で処理する：
    - 1パス目: Item を走査して "警戒" エリアと affected_prefs を収集
    - 2パス目: save_sediment_warnings を1回呼び、単一トランザクションで削除・挿入する
    """
    alerts: list[tuple[str, str]] = []
    affected_prefs: set[str] = set()

    # 1パス目: 警戒エリアと影響都道府県を収集
    for warning_block in root.findall(".//Warning"):
        for item in warning_block.findall("Item"):
            area_el = item.find("Area")
            if area_el is None:
                continue
            area_name = (area_el.findtext("Name") or "").strip()
            area_code = (area_el.findtext("Code") or "").strip()

            pref = get_pref_code_from_area_code(area_code) if area_code else None
            if not pref:
                continue
            affected_prefs.add(pref)

            for kind in item.findall("Kind"):
                # VXWW50では Kind>Name が "警戒" = 警戒情報発令中、"なし" = 対象外
                kind_name = (kind.findtext("Name") or "").strip()
                if kind_name != "警戒":
                    continue
                alerts.append((area_code, area_name))
                break

    # 2パス目: 単一トランザクションで削除・挿入
    saved = save_sediment_warnings(
        pref_codes=affected_prefs,
        alerts=alerts,
        warning_type=SEDIMENT_TYPE,
        reported_at=reported_at,
        db_path=db_path,
    )

    logger.info("土砂災害警戒情報保存: %d件", saved)
    return saved
