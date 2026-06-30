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
from db.models import upsert_warning, delete_warning, delete_warnings_by_types, delete_non_r06_warnings
from fetchers.xml_utils import find_text
from scheduler.area_master import get_pref_code_from_area_code

logger = logging.getLogger(__name__)

# "レベル3大雨注意報" のようなプレフィックスを抽出する正規表現
_LEVEL_RE = re.compile(r"^レベル(\d+)\s*")

# 各 R06 電文種別に対応する、解除・クリア時に削除対象とする警報種別リスト
_R06_CLEANUP_TYPES: dict[str, list[str]] = {
    "VPWW55": ["大雨特別警報（浸水害）", "大雨警報（浸水害）", "大雨注意報（浸水害）"],
    "VPWW56": ["大雨特別警報（土砂災害）", "大雨警報（土砂災害）", "大雨注意報（土砂災害）"],
    "VPWW57": ["高潮特別警報", "高潮警報", "高潮注意報"],
    "VPWW58": ["暴風特別警報", "暴風警報", "強風注意報", "暴風雪特別警報", "暴風雪警報", "風雪注意報"],
    "VPWW59": ["波浪特別警報", "波浪警報", "波浪注意報"],
    "VPWW60": ["大雪特別警報", "大雪警報", "大雪注意報"],
    "VPWW61": ["雷注意報", "融雪注意報", "濃霧注意報", "乾燥注意報", "なだれ注意報", "低温注意報", "霜注意報", "着氷注意報", "着雪注意報"],
}

# VPWW55/56 の衝突防止のために warning_type に付与するサフィックス
_R06_SUFFIX_MAP: dict[str, str] = {
    "VPWW55": "（浸水害）",
    "VPWW56": "（土砂災害）",
}

# R06（VPWW55〜61）でDBに保存される警報種別名（サフィックス付き含む）
_R06_DB_WARNING_TYPES: list[str] = [
    "大雨特別警報（浸水害）", "大雨警報（浸水害）", "大雨注意報（浸水害）",
    "大雨特別警報（土砂災害）", "大雨警報（土砂災害）", "大雨注意報（土砂災害）",
    "高潮特別警報", "高潮警報", "高潮注意報",
    "暴風特別警報", "暴風警報", "強風注意報",
    "暴風雪特別警報", "暴風雪警報", "風雪注意報",
    "波浪特別警報", "波浪警報", "波浪注意報",
    "大雪特別警報", "大雪警報", "大雪注意報",
    "雷注意報", "融雪注意報", "濃霧注意報", "乾燥注意報", "なだれ注意報", "低温注意報", "霜注意報", "着氷注意報", "着雪注意報",
]


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


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VPWW53 XMLを解析して警報・注意報をDBに保存する。

    従来の「都道府県単位で全削除してから再挿入」方式を廃止し、
    Kind/Status ごとに個別 DELETE / upsert を行う（冪等設計）。

    - Kind/Status == "解除" → (area_code, warning_type) を DELETE
    - Kind/Status == "発表" or "継続" → upsert（alert_level も更新）
    - Kind/Name に "なし" が含まれる場合 → area_code の全警報を DELETE

    Returns:
        upsert した件数。
    """
    warning_block = _find_warning_block(root)
    if warning_block is None:
        logger.debug("Warning ブロックが見つかりませんでした")
        return 0

    saved = 0

    for item in warning_block.findall("Item"):
        area_el = item.find("Area")
        if area_el is None:
            continue
        area_name = (area_el.findtext("Name") or "").strip()
        area_code = (area_el.findtext("Code") or "").strip()
        if not area_code:
            continue

        kinds = item.findall("Kind")
        if not kinds:
            # Kind 要素なし = 警報発令なし → エリアの全警報を削除（R06管理分は除く）
            delete_non_r06_warnings(area_code, _R06_DB_WARNING_TYPES, db_path=db_path)
            continue

        # "発表警報・注意報はなし" パターン: Name に "なし" を含む
        has_none = any("なし" in (kind.findtext("Name") or "") for kind in kinds)
        if has_none:
            delete_non_r06_warnings(area_code, _R06_DB_WARNING_TYPES, db_path=db_path)
            continue

        # 今回の電文でアクティブ（発表・継続）な警報種別を収集
        active_types: list[str] = []
        for kind in kinds:
            kind_name = (kind.findtext("Name") or "").strip()
            status = (kind.findtext("Status") or "").strip()
            if status in ("発表", "継続"):
                _, warning_type = _extract_alert_level(kind_name)
                if not warning_type:
                    warning_type = kind_name
                active_types.append(warning_type)

        # 今回アクティブでない、かつR06対象外の警報をDBから一括削除（ゴースト警報の防止）
        delete_non_r06_warnings(area_code, _R06_DB_WARNING_TYPES + active_types, db_path=db_path)

        for kind in kinds:
            kind_name = (kind.findtext("Name") or "").strip()
            status = (kind.findtext("Status") or "").strip()

            alert_level, warning_type = _extract_alert_level(kind_name)
            if not warning_type:
                warning_type = kind_name

            if status in ("発表", "継続"):
                level = _level(warning_type)
                upsert_warning(
                    area_code=area_code,
                    area_name=area_name,
                    warning_type=warning_type,
                    level=level,
                    reported_at=reported_at,
                    alert_level=alert_level,
                    db_path=db_path,
                )
                saved += 1
            elif status == "解除":
                delete_warning(area_code, warning_type, db_path=db_path)
            else:
                logger.debug("未知の Status '%s' (area=%s, type=%s)", status, area_code, warning_type)

    logger.info("警報保存: %d件", saved)
    return saved


def handle_r06(root: etree._Element, reported_at: str, doc_type: str = "", db_path=None) -> int:
    """VPWW55〜61 R06 形式 XMLを解析して警報・注意報をDBに保存する。

    電文種別（doc_type）に対応する警報種別をエリア単位で全削除してから再挿入する（冪等・自己修復設計）。
    """
    warning_block = _find_warning_block(root)
    if warning_block is None:
        logger.debug("[%s] Warning ブロックが見つかりませんでした", doc_type)
        return 0

    saved = 0

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
            continue

        # この電文種別が管理する警報種別をエリア単位で一括削除（ゴースト警報の防止）
        delete_warnings_by_types(area_code, cleanup_types, db_path=db_path)

        kinds = item.findall("Kind")
        for kind in kinds:
            kind_name = (kind.findtext("Name") or "").strip()
            status = (kind.findtext("Status") or "").strip()

            if "なし" in kind_name:
                break

            alert_level, warning_type = _extract_alert_level(kind_name)
            if not warning_type:
                warning_type = kind_name

            suffix = _R06_SUFFIX_MAP.get(doc_type, "")
            if suffix and not warning_type.endswith(suffix):
                warning_type += suffix

            if status in ("発表", "継続"):
                level = _level(warning_type)
                upsert_warning(
                    area_code=area_code,
                    area_name=area_name,
                    warning_type=warning_type,
                    level=level,
                    reported_at=reported_at,
                    alert_level=alert_level,
                    db_path=db_path,
                )
                saved += 1
            else:
                logger.debug("[%s] スキップ Status='%s' (area=%s, type=%s)", doc_type, status, area_code, warning_type)

    logger.info("[%s] 警報保存: %d件", doc_type, saved)
    return saved
