"""VFVO53 降灰予報 パーサー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import upsert_volcano_alert
from fetchers.xml_utils import find_text

logger = logging.getLogger(__name__)


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VFVO53 XMLを解析して降灰予報をDBに保存する。保存件数を返す。"""
    alert_type = find_text(root, "Head/Title") or "降灰予報"

    # VolcanoName タグを全検索して最初の1個を使う
    volcano_el = root.find(".//VolcanoName")
    if volcano_el is None or not volcano_el.text:
        logger.debug("VolcanoName が見つかりませんでした")
        return 0

    volcano_name = volcano_el.text.strip()

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
