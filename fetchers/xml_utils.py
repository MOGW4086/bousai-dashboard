"""JMA XML共通ユーティリティ。"""
import re
import requests
from lxml import etree

ATOM_NS = "http://www.w3.org/2005/Atom"
UA = {"User-Agent": "bousai-dashboard/1.0"}


def strip_ns(content: bytes) -> bytes:
    """XML名前空間を除去。"""
    s = re.sub(rb' xmlns(?::\w+)?="[^"]*"', b'', content)
    s = re.sub(rb'<(\w+):(\w)', rb'<\2', s)
    s = re.sub(rb'</(\w+):(\w)', rb'</\2', s)
    return s


def fetch_xml(url: str) -> "etree._Element | None":
    try:
        resp = requests.get(url, timeout=20, headers=UA)
        resp.raise_for_status()
        return etree.fromstring(strip_ns(resp.content))
    except Exception:
        return None


def fetch_atom(url: str) -> list[dict]:
    """ATOMフィードを取得してエントリリスト（id/title/updated/link）を返す。"""
    try:
        resp = requests.get(url, timeout=20, headers=UA)
        resp.raise_for_status()
        root = etree.fromstring(resp.content)
        ns = {"a": ATOM_NS}
        entries = []
        for e in root.findall("a:entry", ns):
            link_el = e.find("a:link", ns)
            entries.append({
                "id":      e.findtext("a:id",      namespaces=ns) or "",
                "title":   e.findtext("a:title",   namespaces=ns) or "",
                "updated": e.findtext("a:updated", namespaces=ns) or "",
                "link":    link_el.get("href", "") if link_el is not None else "",
            })
        return entries
    except Exception:
        return []


def doc_type(url: str) -> str:
    """URLのファイル名から電文種別コード（VXSE53等）を取得。"""
    filename = url.rsplit("/", 1)[-1]  # 20260603210250_0_VXSE53_010000.xml
    parts = filename.replace(".xml", "").split("_")
    return parts[2] if len(parts) >= 3 else ""


def find_text(root: "etree._Element", *paths: str) -> "str | None":
    for path in paths:
        el = root.find(path)
        if el is not None and el.text:
            return el.text.strip()
    return None
