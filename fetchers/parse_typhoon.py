"""VPTW60 台風解析・予報情報 パーサー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import replace_all_typhoons
from fetchers.xml_utils import find_text

logger = logging.getLogger(__name__)


def _element_to_dict(el: etree._Element, _depth: int = 0) -> dict:
    """lxml Element を再帰的に dict へ変換する（raw_json 用）。"""
    if _depth > 50:
        return {"_truncated": True}
    result: dict = {}
    # テキストノード
    if el.text and el.text.strip():
        result["_text"] = el.text.strip()
    # 属性
    if el.attrib:
        result["_attrib"] = dict(el.attrib)
    # 子要素
    for child in el:
        tag = child.tag
        if not isinstance(tag, str):  # コメントノード・処理命令をスキップ
            continue
        child_dict = _element_to_dict(child, _depth + 1)
        if tag in result:
            existing = result[tag]
            if not isinstance(existing, list):
                result[tag] = [existing]
            result[tag].append(child_dict)
        else:
            result[tag] = child_dict
    return result


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VPTW60 XMLを解析して台風情報をDBに保存する。保存件数を返す。

    全削除→再挿入方式を採用しているため、消滅した台風が残り続けることはない。
    """
    records: list[dict] = []
    seen_ids: set[str] = set()

    meteorological_infos = root.find("Body/MeteorologicalInfos")
    if meteorological_infos is None:
        logger.warning("MeteorologicalInfos が見つかりません")
        return 0

    for info in meteorological_infos.findall("MeteorologicalInfo"):
        # <DateTime type="実況"> のみ処理
        dt_el = info.find("DateTime")
        if dt_el is None:
            continue
        dt_type = dt_el.get("type", "")
        if dt_type != "実況":
            continue

        item = info.find("Item")
        if item is None:
            continue

        # Kind 要素を Type ごとに整理
        kind_map: dict[str, etree._Element] = {}
        for kind in item.findall("Kind"):
            type_text = find_text(kind, "Property/Type")
            if type_text:
                kind_map[type_text] = kind

        # --- typhoon_id: <Number> ---
        name_part = None
        if "呼称" in kind_map:
            name_part = kind_map["呼称"].find("Property/TyphoonNamePart")

        if name_part is None:
            logger.debug("TyphoonNamePart が見つからないためスキップ")
            continue

        typhoon_id = find_text(name_part, "Number")
        if not typhoon_id:
            logger.debug("<Number> が取得できないためスキップ")
            continue

        # 同一電文内の重複 typhoon_id はスキップ（name/status解析・dict変換より先にチェック）
        if typhoon_id in seen_ids:
            logger.debug("typhoon_id=%s は同一電文内で重複のためスキップ", typhoon_id)
            continue
        seen_ids.add(typhoon_id)

        # --- name: "<NameKana>（<Name>）" ---
        name_kana = find_text(name_part, "NameKana")
        name_en = find_text(name_part, "Name")
        if name_kana and name_en:
            name = f"{name_kana}（{name_en}）"
        elif name_kana:
            name = name_kana
        elif name_en:
            name = name_en
        else:
            name = None

        # --- status: <TyphoonClass type="熱帯擾乱種類"> ---
        status = None
        if "階級" in kind_map:
            class_part = kind_map["階級"].find("Property/ClassPart")
            if class_part is not None:
                for tc in class_part.findall("TyphoonClass"):
                    if tc.get("type") == "熱帯擾乱種類":
                        status = tc.text.strip() if tc.text else None
                        break

        # --- raw_json: Item 要素の内容を dict 化 ---
        raw_json = _element_to_dict(item)

        records.append(
            {
                "typhoon_id": typhoon_id,
                "name": name,
                "status": status,
                "raw_json": raw_json,
            }
        )

    # 全削除→再挿入: 解析完了後にまとめて1トランザクションで置換する
    replace_all_typhoons(records, reported_at=reported_at, db_path=db_path)
    for rec in records:
        logger.info("台風保存: typhoon_id=%s name=%s status=%s", rec["typhoon_id"], rec["name"], rec["status"])

    return len(records)
