"""VFVO53 降灰予報 パーサー。"""
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import upsert_volcano_alert
from fetchers.xml_utils import find_text

logger = logging.getLogger(__name__)

# Head/Title 形式: "火山名　桜島　降灰予報（定時）"
_TITLE_RE = re.compile(r"火山名\s*(.+?)\s*降灰")


def _extract_volcano_name(title: str) -> str | None:
    """タイトル文字列から火山名を抽出する。"""
    m = _TITLE_RE.search(title)
    return m.group(1).strip() if m else None


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VFVO53 XMLを解析して降灰予報をDBに保存する。保存件数を返す。"""
    title = find_text(root, "Head/Title") or ""
    alert_type = title or "降灰予報"

    volcano_name = _extract_volcano_name(title)
    if not volcano_name:
        logger.warning("火山名を取得できませんでした: title=%r", title)
        return 0

    upsert_volcano_alert(
        volcano_name=volcano_name,
        alert_level=None,
        alert_type=alert_type,
        description=alert_type,
        reported_at=reported_at,
        db_path=db_path,
    )
    logger.info("降灰予報保存: volcano=%s type=%s", volcano_name, alert_type)
    return 1
