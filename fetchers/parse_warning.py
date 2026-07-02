"""VPWW53 / VPWW55〜61 気象警報・注意報 パーサー。

VPWW53: 従来形式。都道府県単位ですべての警報種別を網羅。
VPWW55〜61: R06 形式。警報種別ごとに分割された新形式。警戒レベル情報を含む。
"""
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import get_conn

logger = logging.getLogger(__name__)

# "レベル3大雨注意報" のようなプレフィックスを抽出する正規表現
_LEVEL_RE = re.compile(r"^レベル(\d+)\s*")

# 各 R06 電文種別に対応する、解除・クリア時に削除対象とする警報種別リスト
_R06_CLEANUP_TYPES: dict[str, list[str]] = {
    "VPWW55": ["大雨特別警報（浸水害）", "大雨危険警報（浸水害）", "大雨警報（浸水害）", "大雨注意報（浸水害）", "洪水警報", "洪水注意報"],
    "VPWW56": ["土砂災害特別警報", "土砂災害危険警報", "土砂災害警報", "土砂災害注意報"],
    "VPWW57": ["高潮特別警報", "高潮危険警報", "高潮警報", "高潮注意報"],
    "VPWW58": ["暴風特別警報", "暴風警報", "強風注意報", "暴風雪特別警報", "暴風雪警報", "風雪注意報"],
    "VPWW59": ["波浪特別警報", "波浪警報", "波浪注意報"],
    "VPWW60": ["大雪特別警報", "大雪警報", "大雪注意報"],
    "VPWW61": ["雷注意報", "融雪注意報", "濃霧注意報", "乾燥注意報", "なだれ注意報", "低温注意報", "霜注意報", "着氷注意報", "着雪注意報", "その他の注意報"],
}

# VPWW55/56 の衝突防止のために warning_type に付与するサフィックス
_R06_SUFFIX_MAP: dict[str, str] = {
    "VPWW55": "（浸水害）",
}


def _level(warning_type: str) -> str:
    """警報種別から level 文字列（advisory/warning/special_warning）を返す。"""
    if "特別警報" in warning_type:
        return "special_warning"
    if "警報" in warning_type:
        return "warning"
    return "advisory"


def _extract_alert_level(kind_name: str) -> tuple[int | None, str]:
    """Kind/Name からレベルプレフィックスを抽出する。

    例:
        "レベル3大雨注意報" → (3, "大雨注意報")
        "大雨注意報"         → (None, "大雨注意報")

    Returns:
        (alert_level, warning_type) のタプル。レベルなしの場合 alert_level は None。
    """
    m = _LEVEL_RE.match(kind_name)
    if m:
        level_int = int(m.group(1))
        if not (1 <= level_int <= 5):
            logger.warning("想定外の alert_level 値: %d (kind_name=%s)", level_int, kind_name)
            return None, kind_name[m.end():]
        return level_int, kind_name[m.end():]
    return None, kind_name


def _find_warning_block(root: etree._Element) -> "etree._Element | None":
    """XML ルートから気象警報・注意報ブロックを探す。"""
    for w in root.findall(".//Warning"):
        wtype = w.get("type", "")
        if "気象警報・注意報" in wtype and "一次細分区域" in wtype:
            return w
    # フォールバック: 最初の Warning ブロック
    return root.find(".//Warning")



def handle_r06(root: etree._Element, reported_at: str, doc_type: str = "", db_path=None) -> int:
    """VPWW55〜61 R06 形式 XMLを解析して警報・注意報をDBに保存する。

    電文種別（doc_type）に対応する警報種別をエリア単位で全削除してから再挿入する（冪等・自己修復設計）。
    全 Item を単一トランザクションで処理し、コミット回数を最小化する。
    """
    warning_block = _find_warning_block(root)
    if warning_block is None:
        logger.debug("[%s] Warning ブロックが見つかりませんでした", doc_type)
        return 0

    saved = 0

    with get_conn(db_path) as conn:
        for item in warning_block.findall("Item"):
            area_el = item.find("Area")
            if area_el is None:
                continue
            area_name = (area_el.findtext("Name") or "").strip()
            area_code = (area_el.findtext("Code") or "").strip()
            if not area_code:
                continue

            cleanup_types = _R06_CLEANUP_TYPES.get(doc_type, [])
            if not cleanup_types:
                logger.warning("[%s] _R06_CLEANUP_TYPES に未登録の doc_type (area=%s)", doc_type, area_code)
            else:
                # この電文種別が管理する警報種別をエリア単位で一括削除（ゴースト警報の防止）
                placeholders = ",".join("?" * len(cleanup_types))
                conn.execute(
                    f"DELETE FROM warnings WHERE area_code=? AND warning_type IN ({placeholders})",
                    (area_code, *cleanup_types),
                )

            kinds = item.findall("Kind")
            for kind in kinds:
                kind_name = (kind.findtext("Name") or "").strip()
                status = (kind.findtext("Status") or "").strip()

                if "なし" in status:
                    break

                alert_level, warning_type = _extract_alert_level(kind_name)
                if not warning_type:
                    warning_type = kind_name

                suffix = _R06_SUFFIX_MAP.get(doc_type, "")
                if suffix and warning_type.startswith("大雨") and not warning_type.endswith(suffix):
                    warning_type += suffix

                if status in ("発表", "継続"):
                    level = _level(warning_type)
                    conn.execute(
                        """
                        INSERT INTO warnings (area_code, area_name, warning_type, level, alert_level, reported_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        ON CONFLICT(area_code, warning_type)
                        DO UPDATE SET area_name=excluded.area_name, level=excluded.level,
                                      alert_level=COALESCE(excluded.alert_level, warnings.alert_level),
                                      reported_at=excluded.reported_at, fetched_at=datetime('now','localtime')
                        WHERE excluded.reported_at IS NULL
                           OR warnings.reported_at IS NULL
                           OR excluded.reported_at >= warnings.reported_at
                        """,
                        (area_code, area_name, warning_type, level, alert_level, reported_at),
                    )
                    saved += 1
                else:
                    logger.debug("[%s] スキップ Status='%s' (area=%s, type=%s)", doc_type, status, area_code, warning_type)

    logger.info("[%s] 警報保存: %d件", doc_type, saved)
    return saved
