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
from db.models import upsert_warning, delete_warning, delete_warnings_by_area, delete_warnings_by_pref
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
    "VPWW58": ["洪水警報", "洪水注意報"],
    "VPWW59": ["暴風特別警報", "暴風警報", "暴風注意報"],
    "VPWW60": ["大雪特別警報", "大雪警報", "大雪注意報"],
    "VPWW61": ["暴風雪特別警報", "暴風雪警報", "暴風雪注意報"],
}

# VPWW55/56 の衝突防止のために warning_type に付与するサフィックス
_R06_SUFFIX_MAP: dict[str, str] = {
    "VPWW55": "（浸水害）",
    "VPWW56": "（土砂災害）",
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
            # Kind 要素なし = 警報発令なし → エリアの全警報を削除
            delete_warnings_by_area(area_code, db_path=db_path)
            continue

        for kind in kinds:
            kind_name = (kind.findtext("Name") or "").strip()
            status = (kind.findtext("Status") or "").strip()

            # "発表警報・注意報はなし" パターン: Name に "なし" を含む
            if "なし" in kind_name:
                delete_warnings_by_area(area_code, db_path=db_path)
                break

            # VPWW53 の Kind/Name にはレベルプレフィックスが付く場合がある
            alert_level, warning_type = _extract_alert_level(kind_name)
            if not warning_type:
                warning_type = kind_name

            if status == "解除":
                delete_warning(area_code, warning_type, db_path=db_path)
            elif status in ("発表", "継続"):
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
                logger.debug("未知の Status '%s' (area=%s, type=%s)", status, area_code, warning_type)

    logger.info("警報保存: %d件", saved)
    return saved


def handle_r06(root: etree._Element, reported_at: str, doc_type: str = "", db_path=None) -> int:
    """VPWW55〜61 R06 形式 XMLを解析して警報・注意報をDBに保存する。

    R06 形式は警報種別ごとに分割されており、Kind/Name にレベルプレフィックスが付く。
    - Kind/Status == "解除" → (area_code, warning_type) を DELETE
    - Kind/Status == "発表" or "継続" → upsert（alert_level を格納）
    - Kind/Name に "なし" を含む → area_code の対象種別を DELETE

    Args:
        root: lxml Element（XML ルート）。
        reported_at: 電文の発表日時文字列。
        doc_type: 電文種別コード（"VPWW55" 等）。警報種別の解決に使用。
        db_path: DB パス。None の場合は Config.DB_PATH を使用。

    Returns:
        upsert した件数。
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

        kinds = item.findall("Kind")
        if not kinds:
            # Kind なし = 発令なし → 電文種別に対応する全警報種別を削除
            cleanup_types = _R06_CLEANUP_TYPES.get(doc_type, [])
            if cleanup_types:
                for wt in cleanup_types:
                    delete_warning(area_code, wt, db_path=db_path)
            else:
                logger.warning("[%s] _R06_CLEANUP_TYPES に未登録の doc_type (area=%s)", doc_type, area_code)
            continue

        for kind in kinds:
            kind_name = (kind.findtext("Name") or "").strip()
            status = (kind.findtext("Status") or "").strip()

            # "なし" パターン → 電文種別に対応する全警報種別を削除
            if "なし" in kind_name:
                cleanup_types = _R06_CLEANUP_TYPES.get(doc_type, [])
                if cleanup_types:
                    for wt in cleanup_types:
                        delete_warning(area_code, wt, db_path=db_path)
                else:
                    logger.warning("[%s] _R06_CLEANUP_TYPES に未登録の doc_type (area=%s, kind_name=%s)", doc_type, area_code, kind_name)
                break

            # R06 では Kind/Name にレベルプレフィックスが必ず付く
            alert_level, warning_type = _extract_alert_level(kind_name)
            if not warning_type:
                warning_type = kind_name

            # VPWW55/56 の衝突防止: warning_type にサフィックスを付与
            suffix = _R06_SUFFIX_MAP.get(doc_type, "")
            if suffix and not warning_type.endswith(suffix):
                warning_type += suffix

            if status == "解除":
                delete_warning(area_code, warning_type, db_path=db_path)
            elif status in ("発表", "継続"):
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
                logger.debug("[%s] 未知の Status '%s' (area=%s, type=%s)", doc_type, status, area_code, warning_type)

    logger.info("[%s] 警報保存: %d件", doc_type, saved)
    return saved
