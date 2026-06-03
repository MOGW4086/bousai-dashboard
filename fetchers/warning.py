"""気象庁警報・注意報JSONを取得するフェッチャー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetchers.base import http_get_json
from db.models import delete_warnings_by_pref, upsert_warning, get_all_pref_codes

logger = logging.getLogger(__name__)

JMA_WARNING_URL = "https://www.jma.go.jp/bosai/warning/data/warning/{pref_code}.json"

# viewer_areas が空の場合の全国主要エリア（47都道府県コード）
DEFAULT_PREF_CODES = [
    "010100", "020000", "030000", "040000", "050000",
    "060000", "070000", "080000", "090000", "100000",
    "110000", "120000", "130000", "140000", "150000",
    "160000", "170000", "180000", "190000", "200000",
    "210000", "220000", "230000", "240000", "250000",
    "260000", "270000", "280000", "290000", "300000",
    "310000", "320000", "330000", "340000", "350000",
    "360000", "370000", "380000", "390000", "400000",
    "410000", "420000", "430000", "440000", "450000",
    "460100", "471000",
]

# 警報種別・レベルのマッピング
LEVEL_MAP = {
    "特別警報": "special_warning",
    "警報": "warning",
    "注意報": "advisory",
}


def _parse_warning_data(pref_code: str, data: dict, db_path: str | None) -> int:
    """警報JSONをパースしてDBにupsertする。保存件数を返す。"""
    saved = 0
    areas = data.get("areaTypes", [])
    for area_type in areas:
        for area in area_type.get("areas", []):
            area_code = area.get("code", "")
            area_name = area.get("name", "")
            for warning in area.get("warnings", []):
                w_type = warning.get("name", "")
                status = warning.get("status", "")
                if status == "解除" or not w_type:
                    continue
                level = LEVEL_MAP.get(warning.get("level", ""), "advisory")
                reported_at = data.get("reportDatetime")
                upsert_warning(
                    area_code=area_code,
                    area_name=area_name,
                    warning_type=w_type,
                    level=level,
                    reported_at=reported_at,
                    db_path=db_path,
                )
                saved += 1
    return saved


def fetch(db_path: str | None = None) -> int:
    """登録地域の都道府県ごとに警報JSONを取得・保存する。保存件数を返す。"""
    pref_codes = get_all_pref_codes(db_path=db_path) or DEFAULT_PREF_CODES

    total = 0
    for pref_code in pref_codes:
        url = JMA_WARNING_URL.format(pref_code=pref_code)
        data = http_get_json(url)
        if data is None:
            logger.warning("警報データ取得失敗: pref_code=%s", pref_code)
            continue

        delete_warnings_by_pref(pref_code, db_path=db_path)
        count = _parse_warning_data(pref_code, data, db_path)
        total += count
        logger.debug("警報: pref_code=%s, %d件", pref_code, count)

    logger.info("警報情報: 合計%d件保存", total)
    return total
