"""JMA ATOMフィード メインディスパッチャー。"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fetchers.xml_utils import fetch_atom, fetch_xml, doc_type
from fetchers import parse_quake, parse_warning, parse_sediment, parse_volcano, parse_heatstroke, parse_typhoon, parse_tsunami
from db.models import is_processed, mark_processed

logger = logging.getLogger(__name__)

FEEDS = {
    "eqvol": "https://www.data.jma.go.jp/developer/xml/feed/eqvol_l.xml",
    "extra": "https://www.data.jma.go.jp/developer/xml/feed/extra_l.xml",
}

HANDLERS = {
    "VXSE53": parse_quake.handle,
    # VPWW55〜61: R06 形式 警報・注意報（警報種別ごとに分割・警戒レベル付き）
    # VPWW55: 大雨（浸水害）, VPWW56: 大雨（土砂災害）, VPWW57: 高潮
    # VPWW58: 暴風（暴風雪含む）, VPWW59: 波浪, VPWW60: 大雪, VPWW61: その他注意報
    **{
        f"VPWW{i}": (lambda dt: lambda root, reported_at, **kw: parse_warning.handle_r06(root, reported_at, doc_type=dt, **kw))(f"VPWW{i}")
        for i in range(55, 62)
    },
    "VXWW50": parse_sediment.handle,
    "VFVO50": parse_volcano.handle_vfvo50,
    "VFVO52": parse_volcano.handle_vfvo52,
    "VFVO53": parse_volcano.handle,
    "VPFT50": parse_heatstroke.handle,
    # VPTW60〜VPTW65: 台風解析・予報情報（５日予報）（H30形式）
    # 気象庁XML仕様 表1.1 通番9: VPTWii (ii=60-65)
    **{f"VPTW6{i}": parse_typhoon.handle for i in range(6)},
    "VTWW53": lambda root, reported_at, **kw: parse_tsunami.handle(root, reported_at, telegram_type="VTWW53", **kw),
    # 遠地地震の津波警報・注意報・予報は VTSE41 として配信される（エリアコードは 010000 共通）
    "VTSE41": lambda root, reported_at, **kw: parse_tsunami.handle(root, reported_at, telegram_type="VTSE41", **kw),
}

# 同一都道府県の最新1件のみ処理する電文種別（地域フィルタが必要なもの）
# VTSE41 はエリアコード 010000 が全エリア共通のため重複排除対象外とする
# VXWW50 は一県全域を網羅するため、古い電文で最新状態が上書きされないよう最新1件のみ処理する
# VPWW55〜61 も警報種別ごとに地域単位で配信されるため重複排除対象に追加する
_AREA_DEDUP_TYPES = {"VTWW53", "VXWW50"} | {f"VPWW{i}" for i in range(55, 62)}


def _area_code_from_url(url: str) -> str:
    """URLのファイル名末尾の数値部分（都道府県コード相当）を取得。
    例: 20260603210250_0_VPWW53_140000.xml → "140000"
         20260626065305_0_VXWW50_340000.xml → "340000"
    """
    filename = url.rsplit("/", 1)[-1]
    parts = filename.replace(".xml", "").split("_")
    return parts[3] if len(parts) >= 4 else ""


def fetch(db_path=None) -> int:
    """全フィードを取得し、未処理エントリをハンドラーに渡す。処理件数を返す。"""
    total = 0

    for feed_name, feed_url in FEEDS.items():
        logger.info("[%s] フィード取得: %s", feed_name, feed_url)
        entries = fetch_atom(feed_url)
        if not entries:
            logger.warning("[%s] エントリが取得できませんでした", feed_name)
            continue

        logger.info("[%s] エントリ数: %d", feed_name, len(entries))

        # 未処理エントリを抽出し、電文種別ごとに分類
        unprocessed: list[dict] = []
        for entry in entries:
            if not is_processed(entry["id"], db_path=db_path):
                unprocessed.append(entry)

        logger.info("[%s] 未処理: %d件", feed_name, len(unprocessed))

        # 地域重複排除が必要な種別は area_code × doc_type で最新1件のみ残す
        deduped: list[dict] = []
        seen_area: dict[tuple[str, str], str] = {}  # (dtype, area_code) → entry_id of best

        for entry in unprocessed:
            link = entry.get("link", "")
            dtype = doc_type(link)

            if dtype in _AREA_DEDUP_TYPES:
                area = _area_code_from_url(link)
                key = (dtype, area)
                existing_id = seen_area.get(key)
                if existing_id is None:
                    seen_area[key] = entry["id"]
                    deduped.append(entry)
                else:
                    # 更新日時が新しい方を優先
                    existing = next((e for e in deduped if e["id"] == existing_id), None)
                    if existing and entry["updated"] > existing["updated"]:
                        deduped.remove(existing)
                        # 古いエントリは処理済みとしてスキップ（ダウンロードしない）
                        mark_processed(existing["id"], db_path=db_path)
                        seen_area[key] = entry["id"]
                        deduped.append(entry)
                    else:
                        # 古い方をスキップ済みにする
                        mark_processed(entry["id"], db_path=db_path)
            else:
                deduped.append(entry)

        # 各エントリを処理
        for entry in deduped:
            link = entry.get("link", "")
            if not link:
                mark_processed(entry["id"], db_path=db_path)
                continue

            dtype = doc_type(link)
            handler = HANDLERS.get(dtype)

            if handler is None:
                # 対象外電文は処理済みとしてマーク（再処理しない）
                mark_processed(entry["id"], db_path=db_path)
                continue

            logger.info("[%s] 処理: %s (updated=%s)", dtype, link, entry["updated"])
            root = fetch_xml(link)
            if root is None:
                logger.error("XML取得失敗: %s", link)
                mark_processed(entry["id"], db_path=db_path)
                continue

            try:
                count = handler(root, entry["updated"], db_path=db_path)
                total += count
            except Exception as e:
                logger.error("ハンドラーエラー [%s]: %s", dtype, e)

            mark_processed(entry["id"], db_path=db_path)

    logger.info("ATOMフィード処理完了: 合計%d件", total)
    return total
