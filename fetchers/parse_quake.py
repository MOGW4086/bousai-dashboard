"""VXSE53 震源・震度情報 パーサー。"""
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import insert_quake
from fetchers.xml_utils import find_text

logger = logging.getLogger(__name__)

INTENSITY_MAP = {
    "1": 10,
    "2": 20,
    "3": 30,
    "4": 40,
    "5弱": 50,
    "5強": 55,
    "6弱": 60,
    "6強": 65,
    "7": 70,
}

MIN_SCALE = 0  # 全震度を保存（表示フィルタはUIで行う）


def _parse_coordinate(text: str | None) -> tuple[float | None, float | None]:
    """ISO 6709 形式の座標文字列から (latitude, longitude) を返す。

    例: +35.679+140.090-60000/ → lat=35.679, lon=140.090
    """
    if not text:
        return None, None
    m = re.match(r'([+-]\d+\.?\d*)([+-]\d+\.?\d*)', text.strip())
    if not m:
        return None, None
    try:
        lat, lon = float(m.group(1)), float(m.group(2))
        if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
            return lat, lon
        return None, None
    except ValueError:
        return None, None


def _parse_scale(text: str | None) -> int | None:
    if text is None:
        return None
    return INTENSITY_MAP.get(text.strip())


# VXSE53 ForecastComment/Code の津波コード定義
# 0201/0213: 津波の心配なし、0202系: 若干の海面変動（被害なし）、その他: 津波情報あり
TSUNAMI_CODE_MAP = {
    "0201": "なし",
    "0213": "なし",
}


def _parse_tsunami_code(code: str | None) -> str:
    """VXSE53 ForecastComment/Code から津波状況を表す日本語文字列を返す。

    Args:
        code: 気象庁XMLの Body/Comments/ForecastComment/Code の値。

    Returns:
        "なし" / "軽微" / "あり" のいずれか。コードが取得できない場合は "なし"。
    """
    if not code or not code.strip():
        return "なし"
    cleaned_code = code.strip()
    if cleaned_code in TSUNAMI_CODE_MAP:
        return TSUNAMI_CODE_MAP[cleaned_code]
    if cleaned_code.startswith("02"):
        return "軽微"
    return "あり"


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VXSE53 XMLを解析して地震情報をDBに保存する。保存件数（0 or 1）を返す。"""
    event_id = find_text(root, "Head/EventID")
    occurred_at = find_text(root, "Head/ReportDateTime")
    hypocenter = find_text(root, "Body/Earthquake/Hypocenter/Area/Name")
    magnitude_str = find_text(root, "Body/Earthquake/Magnitude")
    max_int_str = find_text(root, "Body/Intensity/Observation/MaxInt")
    tsunami_code = find_text(root, "Body/Comments/ForecastComment/Code")
    coord_text = find_text(root, "Body/Earthquake/Hypocenter/Area/Coordinate")
    latitude, longitude = _parse_coordinate(coord_text)

    magnitude = None
    if magnitude_str:
        try:
            magnitude = float(magnitude_str)
        except ValueError:
            pass

    max_scale = _parse_scale(max_int_str)

    if max_scale is None or max_scale < MIN_SCALE:
        logger.debug("震度フィルタで除外: max_int=%s max_scale=%s", max_int_str, max_scale)
        return 0

    tsunami = _parse_tsunami_code(tsunami_code)

    if not event_id:
        logger.warning("EventID が取得できませんでした")
        return 0

    saved = insert_quake(
        event_id=event_id,
        occurred_at=occurred_at or reported_at,
        hypocenter=hypocenter,
        magnitude=magnitude,
        max_scale=max_scale,
        tsunami=tsunami,
        raw_json=None,
        latitude=latitude,
        longitude=longitude,
        db_path=db_path,
    )
    if saved:
        logger.info("地震保存: event_id=%s max_scale=%d", event_id, max_scale)
        return 1
    return 0
