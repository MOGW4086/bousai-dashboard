"""気象庁警報・注意報JSONを取得するフェッチャー。

APIエンドポイント（全国一括）:
  https://www.jma.go.jp/bosai/warning/data/r8/map.json

JMA bosai warning API は warnings[].name ではなく warnings[].code（数値文字列）を使う。
このファイルに code → (名称, level) のマッピングを保持する。

土砂災害警戒情報は code=49（土砂災害危険警報）として発令される。
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetchers.base import http_get_json
from db.models import delete_warnings_by_pref, get_all_pref_codes, upsert_warning

logger = logging.getLogger(__name__)

# 全国一括取得エンドポイント（最新状態のみ返す）
JMA_WARNING_MAP_URL = "https://www.jma.go.jp/bosai/warning/data/r8/map.json"

# JMA bosai warning API の数値コード → (表示名, level文字列) マッピング
# JMA bosai JS (map.html) の Warning.Common.code2WarningInfo() 実装から抽出
CODE_MAP: dict[str, tuple[str, str]] = {
    # 大雨系（rain/landslide）
    "03": ("大雨警報", "warning"),
    "10": ("大雨注意報", "advisory"),
    "33": ("大雨特別警報", "special_warning"),
    "43": ("大雨危険警報", "special_warning"),
    # 土砂災害系（landslide）
    "09": ("大雨警報（土砂災害）", "warning"),
    "29": ("大雨注意報（土砂災害）", "advisory"),
    "39": ("土砂災害特別警報", "special_warning"),
    "49": ("土砂災害警戒情報", "special_warning"),  # 土砂災害危険警報 = 土砂災害警戒情報
    # 高潮系（tide）
    "08": ("高潮警報", "warning"),
    "19": ("高潮注意報", "advisory"),
    "38": ("高潮特別警報", "special_warning"),
    "48": ("高潮危険警報", "special_warning"),
    # 暴風系（wind）
    "05": ("暴風警報", "warning"),
    "15": ("強風注意報", "advisory"),
    "35": ("暴風特別警報", "special_warning"),
    # 暴風雪系（wind_snow）
    "02": ("暴風雪警報", "warning"),
    "13": ("風雪注意報", "advisory"),
    "32": ("暴風雪特別警報", "special_warning"),
    # 大雪系（snow）
    "06": ("大雪警報", "warning"),
    "12": ("大雪注意報", "advisory"),
    "36": ("大雪特別警報", "special_warning"),
    # 波浪系（wave）
    "07": ("波浪警報", "warning"),
    "16": ("波浪注意報", "advisory"),
    "37": ("波浪特別警報", "special_warning"),
    # 単品注意報
    "14": ("雷注意報", "advisory"),
    "17": ("融雪注意報", "advisory"),
    "20": ("濃霧注意報", "advisory"),
    "21": ("乾燥注意報", "advisory"),
    "22": ("なだれ注意報", "advisory"),
    "23": ("低温注意報", "advisory"),
    "24": ("霜注意報", "advisory"),
    "25": ("着氷注意報", "advisory"),
    "26": ("着雪注意報", "advisory"),
}

ACTIVE_STATUSES = {"発表", "継続", "警報から注意報"}

# viewer_areas が空の場合のデフォルト対象都道府県コード
DEFAULT_PREF_CODES = {
    "130000", "140000", "110000", "120000",
    "270000", "280000", "260000",
    "230000", "220000",
    "400000",
}


def _pref_code_of_area(area_code: str) -> str:
    """エリアコードから6桁都道府県コードを導出する。

    class10s (6桁): 先頭3桁 + "000"  (例 130010 → 130000, 011000 → 011000)
    class20s (7桁):
      先頭が "0" (北海道) → 先頭3桁 + "000"  (例 0121400 → 012000)
      それ以外           → 先頭2桁 + "0000"  (例 1310100 → 130000)
    """
    if len(area_code) == 6:
        return area_code[:3] + "000"
    if area_code and area_code[0] == "0":
        return area_code[:3] + "000"
    return area_code[:2] + "0000"


def fetch(db_path: str | None = None) -> int:
    """全国警報・注意報を取得・保存する。保存件数を返す。"""
    data = http_get_json(
        JMA_WARNING_MAP_URL,
        headers={"Referer": "https://www.jma.go.jp/bosai/map.html"},
    )
    if data is None:
        logger.warning("警報データ取得失敗")
        return 0

    if not isinstance(data, list):
        logger.error("想定外のレスポンス形式: %s", type(data))
        return 0

    pref_codes = set(get_all_pref_codes(db_path=db_path)) or DEFAULT_PREF_CODES

    # map.json はランダム順のため、エリアごとに最新 controlDatetime のエントリを選択
    # area_code → {"controlDatetime": str, "reportDatetime": str, "kinds": list}
    latest: dict[str, dict] = {}

    for entry in data:
        if not isinstance(entry, dict):
            continue
        ctrl_dt = entry.get("controlDatetime", "")
        reported_at = entry.get("reportDatetime")
        warning_block = entry.get("warning", {})

        for item_key in ("class20Items", "class10Items"):
            for item in warning_block.get(item_key, []):
                area_code = item.get("areaCode", "")
                if not area_code:
                    continue
                pref_code = _pref_code_of_area(area_code)
                if pref_code not in pref_codes:
                    continue
                existing = latest.get(area_code)
                if existing is None or ctrl_dt > existing["controlDatetime"]:
                    latest[area_code] = {
                        "controlDatetime": ctrl_dt,
                        "reportDatetime": reported_at,
                        "kinds": item.get("kinds", []),
                    }

    # 対象都道府県の前回分を全削除してから挿入
    for pref_code in pref_codes:
        delete_warnings_by_pref(pref_code, db_path=db_path)

    saved = 0
    for area_code, info in latest.items():
        reported_at = info["reportDatetime"]
        for kind in info["kinds"]:
            code = kind.get("code", "")
            status = kind.get("status", "")
            if status not in ACTIVE_STATUSES or not code:
                continue
            name, level = CODE_MAP.get(code, (f"警報コード{code}", "advisory"))
            upsert_warning(
                area_code=area_code,
                area_name=None,
                warning_type=name,
                level=level,
                reported_at=reported_at,
                db_path=db_path,
            )
            saved += 1

    logger.info("警報・注意報: %d件保存", saved)
    return saved
