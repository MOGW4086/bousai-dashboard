"""VTWW53 津波警報・注意報・予報 パーサー。

気象庁 VTWW53 電文の XML 構造（名前空間除去後）:
  Report
    Head
      ...
    Body
      Tsunami
        Forecast
          Item
            Area
              Name   (地域名)
              Code   (地域コード)
            Category
              Kind
                Name  (MajorWarning / Warning / Advisory / Forecast)
                LastKind
                  Name  (前回の種別)
          ...

NOTE: 実際の電文が手元にないため、気象庁防災情報XMLフォーマット仕様書
      (V2.1) の記載をもとに実装しています。
      電文を受信した際に Category/Kind/Name のパスが異なる場合は
      TODO コメントを参照して調整してください。
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lxml import etree
from db.models import replace_all_tsunami_warnings
from fetchers.xml_utils import find_text

logger = logging.getLogger(__name__)

# 気象庁電文の Category/Kind/Name 値 → 表示文字列マッピング
# 仕様書 (V2.1) 付表に基づく。実電文で異なる値が来た場合はそのまま格納する。
CATEGORY_MAP = {
    "MajorWarning": "大津波警報",
    "Warning": "津波警報",
    "Advisory": "津波注意報",
    "Forecast": "津波予報",
    # 日本語で送出される場合も考慮
    "大津波警報": "大津波警報",
    "津波警報": "津波警報",
    "津波注意報": "津波注意報",
    "津波予報": "津波予報",
}

# 解除・なし扱いのカテゴリ（DBに保存しない）
_NO_THREAT_CATEGORIES = {"None", "解除", "不明", ""}


def handle(root: etree._Element, reported_at: str, db_path=None) -> int:
    """VTWW53 XMLを解析して津波警報情報をDBに保存する。保存件数を返す。

    VTWW53 電文を受信するたびに全件削除して再挿入する（完全上書き方式）。
    """
    body = root.find("Body")
    if body is None:
        logger.warning("Body が見つかりません")
        return 0

    # Body/Tsunami/Forecast/Item を探す（仕様書 V2.1 準拠）
    # TODO: 実電文のタグ構造が異なる場合はここを調整
    tsunami_el = body.find("Tsunami")
    if tsunami_el is None:
        # 解除電文など Tsunami 要素が存在しない場合は DB を全削除して終了
        logger.info("Tsunami 要素なし（解除電文）: DB の津波警報を全削除します")
        replace_all_tsunami_warnings([], db_path=db_path)
        return 0

    forecast_el = tsunami_el.find("Forecast")
    if forecast_el is None:
        # Forecast タグなしで直接 Item が並ぶ構造にも対応
        forecast_el = tsunami_el

    # 有効な警報レコードを収集してからatomicに一括保存する
    warning_rows: list[tuple[str, str | None, str | None, str | None]] = []

    for item in forecast_el.findall("Item"):
        area_el = item.find("Area")
        if area_el is None:
            continue

        area_code = find_text(area_el, "Code") or ""
        area_name = find_text(area_el, "Name")

        # カテゴリは Category/Kind/Name を優先し、Kind/Name にフォールバック
        # TODO: 実電文のパスが異なる場合はここを調整
        category_en = (
            find_text(item, "Category/Kind/Name")
            or find_text(item, "Category/Name")
            or find_text(item, "Kind/Name")
            or ""
        )
        category = CATEGORY_MAP.get(category_en, category_en)

        if not area_code:
            logger.debug("area_code が空のためスキップ: area_name=%s", area_name)
            continue

        if category_en in _NO_THREAT_CATEGORIES:
            logger.debug("解除・脅威なしのためスキップ: area=%s category=%s", area_name, category_en)
            continue

        warning_rows.append((area_code, area_name, category, reported_at))
        logger.info("津波情報収集: area=%s category=%s", area_name, category)

    # 全削除 + 一括挿入をatomicトランザクションで実行
    replace_all_tsunami_warnings(warning_rows, db_path=db_path)
    total = len(warning_rows)
    logger.info("津波警報保存: %d件", total)
    return total
