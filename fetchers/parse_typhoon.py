"""VPTW60 台風解析・予報情報 パーサー。"""
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import upsert_typhoon
from fetchers.xml_utils import find_text

logger = logging.getLogger(__name__)


def _element_to_dict(el: etree._Element, _depth: int = 0) -> dict:
    """lxml Element を再帰的に dict へ変換する（raw_json 用）。"""
    if _depth > 50:
        return {"_truncated": True}
    result: dict = {}
    if el.text and el.text.strip():
        result["_text"] = el.text.strip()
    if el.attrib:
        result["_attrib"] = dict(el.attrib)
    for child in el:
        tag = child.tag
        if not isinstance(tag, str):
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


def _dms_digits_to_decimal(digits: str, deg_len: int) -> float | None:
    """JMA ISO 6709 の純数字 DDMM / DDMMSS 形式を10進度に変換する。
    deg_len: 度部分の桁数（緯度=2, 経度=3）
    """
    n = len(digits)
    if n == deg_len:
        return float(digits)
    if n == deg_len + 2:
        return int(digits[:deg_len]) + int(digits[deg_len:]) / 60
    if n == deg_len + 4:
        return int(digits[:deg_len]) + int(digits[deg_len:deg_len + 2]) / 60 + int(digits[deg_len + 2:]) / 3600
    return None


def _parse_coordinate(text: str) -> tuple[float | None, float | None]:
    """ISO 6709 形式の座標文字列から (latitude, longitude) を返す。
    JMA VPTW60 で使用される形式:
      +DDMM+DDDMM/       → 度分（JMA標準: +2510+13020/）
      +DDMMSS+DDDMMSS/   → 度分秒（+353612+1394530/）
      +DD.D+DDD.D/        → 10進度
      +DDdMMm+DDDdMMm/   → 記号付き度分
    """
    if not text:
        return None, None
    text = text.strip().rstrip("/")

    # 10進度形式（小数点あり）: +DD.D+DDD.D
    if "." in text:
        m = re.match(r"^([+-]\d+\.\d*)([+-]\d+\.\d*)$", text)
        if m:
            try:
                return float(m.group(1)), float(m.group(2))
            except ValueError:
                pass
        return None, None

    # 記号付き度分秒形式: +DDdMMm[SSs]+DDDdMMm[SSs]
    m = re.match(r"^([+-])(\d+)d(\d+)m(?:(\d+)s)?([+-])(\d+)d(\d+)m(?:(\d+)s)?$", text)
    if m:
        lat_sign = -1 if m.group(1) == "-" else 1
        lat = lat_sign * (int(m.group(2)) + int(m.group(3)) / 60 + int(m.group(4) or 0) / 3600)
        lon_sign = -1 if m.group(5) == "-" else 1
        lon = lon_sign * (int(m.group(6)) + int(m.group(7)) / 60 + int(m.group(8) or 0) / 3600)
        return lat, lon

    # 純数字形式（JMA VPTW60 標準）: ±DDMM±DDDMM または ±DDMMSS±DDDMMSS
    m = re.match(r"^([+-])(\d{2,6})([+-])(\d{3,7})$", text)
    if m:
        lat_sign = -1 if m.group(1) == "-" else 1
        lon_sign = -1 if m.group(3) == "-" else 1
        lat = _dms_digits_to_decimal(m.group(2), 2)
        lon = _dms_digits_to_decimal(m.group(4), 3)
        if lat is not None and lon is not None:
            return lat_sign * lat, lon_sign * lon

    return None, None


def _build_kind_map(item: etree._Element) -> dict[str, etree._Element]:
    """Item 要素の Kind を Property/Type をキーにした辞書にまとめる。"""
    kind_map: dict[str, etree._Element] = {}
    for kind in item.findall("Kind"):
        type_text = find_text(kind, "Property/Type")
        if type_text:
            kind_map[type_text] = kind
    return kind_map


def _extract_position(kind_map: dict[str, etree._Element]) -> tuple[float | None, float | None]:
    """kind_map から現在位置の (latitude, longitude) を返す。
    JMA VPTW60 では Type="中心" 配下の CenterPart/Coordinate に実況位置が入る。
    """
    for key, kind in kind_map.items():
        if "位置" in key or "中心" in key:
            coord_text = find_text(kind, "Property/CenterPart/Coordinate")
            if coord_text:
                return _parse_coordinate(coord_text)
    return None, None


def _extract_track(meteorological_infos: etree._Element) -> list[dict]:
    """MeteorologicalInfos から全ての位置情報（実況・予報）を時系列順に抽出する。"""
    track = []
    for info in meteorological_infos.findall("MeteorologicalInfo"):
        dt_el = info.find("DateTime")
        if dt_el is None:
            continue
        dt_type = dt_el.get("type", "")
        dt_text = dt_el.text.strip() if dt_el.text else None

        item = info.find("Item")
        if item is None:
            continue

        for kind in item.findall("Kind"):
            type_text = find_text(kind, "Property/Type")
            if not type_text or ("位置" not in type_text and "中心" not in type_text):
                continue
            # 実況: CenterPart/Coordinate、予報: ProbabilityCircle/BasePoint（type="中心位置（度）"）
            coord_text = find_text(kind, "Property/CenterPart/Coordinate")
            if not coord_text:
                for bp in kind.findall("Property/CenterPart/ProbabilityCircle/BasePoint"):
                    if bp.get("type", "") == "中心位置（度）" and bp.text:
                        coord_text = bp.text.strip()
                        break
            if not coord_text:
                continue
            lat, lon = _parse_coordinate(coord_text)
            if lat is None or lon is None:
                continue
            entry: dict = {"kind": dt_type, "at": dt_text, "lat": lat, "lon": lon}
            # 予報円半径（ProbabilityCircle/Axes/Axis/Radius、単位は "海里" または "km"）
            for radius_el in kind.findall("Property/CenterPart/ProbabilityCircle/Axes/Axis/Radius"):
                radius_type = radius_el.get("type", "")
                unit = radius_el.get("unit", "km")
                try:
                    r_km = int(radius_el.text.strip())
                    if unit.lower() in ("nm", "海里"):
                        r_km = round(r_km * 1.852)
                    if "70" in radius_type or "７０" in radius_type:
                        entry["forecast_radius_70"] = r_km
                    else:
                        entry.setdefault("forecast_radius", r_km)
                except (ValueError, AttributeError):
                    pass
            track.append(entry)
            break
    return track


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VPTW60 XMLを解析して台風情報をDBに保存する。保存件数を返す。"""
    total = 0
    seen_ids: set[str] = set()

    meteorological_infos = root.find("Body/MeteorologicalInfos")
    if meteorological_infos is None:
        logger.warning("MeteorologicalInfos が見つかりません")
        return 0

    # VPTW60 は1電文1台風のため、MeteorologicalInfos 全体のトラックを唯一の台風に紐付ける。
    # 将来的に複数台風が1電文に含まれる場合は予報エントリへの typhoon_id 付与が必要。
    track = _extract_track(meteorological_infos)

    for info in meteorological_infos.findall("MeteorologicalInfo"):
        dt_el = info.find("DateTime")
        if dt_el is None:
            continue
        if dt_el.get("type", "") != "実況":
            continue

        item = info.find("Item")
        if item is None:
            continue

        kind_map = _build_kind_map(item)

        # typhoon_id
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
        if typhoon_id in seen_ids:
            logger.debug("typhoon_id=%s は同一電文内で重複のためスキップ", typhoon_id)
            continue
        seen_ids.add(typhoon_id)

        # name
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

        # status
        status = None
        if "階級" in kind_map:
            class_part = kind_map["階級"].find("Property/ClassPart")
            if class_part is not None:
                for tc in class_part.findall("TyphoonClass"):
                    if tc.get("type") == "熱帯擾乱種類":
                        status = tc.text.strip() if tc.text else None
                        break

        # 現在位置
        latitude, longitude = _extract_position(kind_map)

        raw_json = _element_to_dict(item)

        upsert_typhoon(
            typhoon_id=typhoon_id,
            name=name,
            status=status,
            raw_json=raw_json,
            reported_at=reported_at,
            latitude=latitude,
            longitude=longitude,
            track_json=track,
            db_path=db_path,
        )
        logger.info(
            "台風保存: typhoon_id=%s name=%s status=%s lat=%s lon=%s track_points=%d",
            typhoon_id, name, status, latitude, longitude, len(track),
        )
        total += 1

    return total
