"""VFVO50/52/53 火山情報パーサー。"""
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import upsert_volcano_alert
from fetchers.xml_utils import find_text

logger = logging.getLogger(__name__)

# VFVO53 (降灰予報) 用パターン
_TITLE_ASH_RE = re.compile(r"火山名\s+(.+?)\s+降灰")
_SUBTYPE_RE = re.compile(r"(降灰予報(?:[（(][^）)]+[）)])?)")

# 噴火警報・予報種別抽出用パターン
_ALERT_TYPE_RE = re.compile(r"(噴火(?:警報|予報)[^\n　]*)")


def handle_vfvo50(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VFVO50 噴火警報・予報パーサー。"""
    total = 0
    for vi in root.findall(".//VolcanoInfo"):
        if vi.get("type", "") != "噴火警報・予報（対象火山）":
            continue
        item = vi.find("Item")
        if item is None:
            continue
        kind = item.find("Kind")
        if kind is None:
            continue

        kind_code = find_text(kind, "Code") or ""
        kind_name = find_text(kind, "Name") or ""

        # 噴火警戒レベル: コード 11→1, 12→2, ..., 15→5
        try:
            alert_level = int(kind_code) - 10
            if not 1 <= alert_level <= 5:
                alert_level = None
        except (ValueError, TypeError):
            alert_level = None

        area = item.find("Areas/Area")
        volcano_name = find_text(area, "Name") if area is not None else None
        if not volcano_name:
            logger.warning("VFVO50: 火山名を取得できませんでした")
            continue

        description = (
            find_text(root, ".//VolcanoInfoContent/VolcanoHeadline") or kind_name
        )

        title = find_text(root, "Head/Title") or ""
        m = _ALERT_TYPE_RE.search(title)
        alert_type = m.group(1).strip() if m else "噴火警報・予報"

        upsert_volcano_alert(
            volcano_name=volcano_name,
            alert_level=alert_level,
            alert_type=alert_type,
            description=description,
            reported_at=reported_at,
            db_path=db_path,
        )
        logger.info(
            "噴火警報保存: volcano=%s level=%s type=%s", volcano_name, alert_level, alert_type
        )
        total += 1
        break  # 1電文1火山

    return total


def handle_vfvo52(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VFVO52 噴火に関する火山観測報パーサー。"""
    vi = root.find(".//VolcanoInfo[@type='噴火に関する火山観測報']")
    if vi is None:
        vi = root.find(".//VolcanoInfo")
    if vi is None:
        return 0

    item = vi.find("Item")
    if item is None:
        return 0

    area = item.find("Areas/Area")
    volcano_name = find_text(area, "Name") if area is not None else None
    if not volcano_name:
        logger.warning("VFVO52: 火山名を取得できませんでした")
        return 0

    kind_name = find_text(item, "Kind/Name") or "噴火"
    event_time = find_text(item, "EventTime/EventDateTime") or reported_at

    desc_parts = [f"種別: {kind_name}", f"観測時刻: {event_time}"]
    obs = root.find(".//VolcanoObservation")
    if obs is not None:
        height = find_text(obs, "ColorPlume/PlumeHeightAboveCrater")
        direction = find_text(obs, "ColorPlume/PlumeDirection")
        other = find_text(obs, "OtherObservation")
        if height:
            desc_parts.append(f"噴煙高度: 火口上{height}m")
        if direction:
            desc_parts.append(f"噴煙方向: {direction}")
        if other:
            desc_parts.append(other.strip())

    upsert_volcano_alert(
        volcano_name=volcano_name,
        alert_level=None,
        alert_type="噴火に関する火山観測報",
        description="\n".join(desc_parts),
        reported_at=reported_at,
        db_path=db_path,
    )
    logger.info("噴火観測報保存: volcano=%s kind=%s", volcano_name, kind_name)
    return 1


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VFVO53 降灰予報パーサー。"""
    title = find_text(root, "Head/Title") or ""
    alert_type = _extract_alert_type(title)
    volcano_name = _extract_volcano_name(title)
    if not volcano_name:
        logger.warning("火山名を取得できませんでした: title=%r", title)
        return 0
    upsert_volcano_alert(
        volcano_name=volcano_name,
        alert_level=None,
        alert_type=alert_type,
        description=title,
        reported_at=reported_at,
        db_path=db_path,
    )
    logger.info("降灰予報保存: volcano=%s type=%s", volcano_name, alert_type)
    return 1


def _extract_volcano_name(title: str) -> str | None:
    m = _TITLE_ASH_RE.search(title)
    return m.group(1).strip() if m else None


def _extract_alert_type(title: str) -> str:
    m = _SUBTYPE_RE.search(title)
    return m.group(1).strip() if m and m.group(1) else "降灰予報"
