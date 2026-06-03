"""フェッチャー基底モジュール。HTTP取得ユーティリティを提供する。"""
import logging

import requests
from lxml import etree

logger = logging.getLogger(__name__)


def http_get_json(url: str, timeout: int = 10, headers: dict | None = None) -> dict | list | None:
    """GETリクエストでJSONを取得する。エラー時はNoneを返す。"""
    merged = {"User-Agent": "bousai-dashboard/1.0"}
    if headers:
        merged.update(headers)
    try:
        resp = requests.get(url, timeout=timeout, headers=merged)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.Timeout:
        logger.error("Timeout: %s", url)
    except requests.exceptions.HTTPError as e:
        logger.error("HTTP error %s: %s", e.response.status_code, url)
    except requests.exceptions.RequestException as e:
        logger.error("Request failed (%s): %s", e, url)
    except ValueError as e:
        logger.error("JSON decode error (%s): %s", e, url)
    return None


def http_get_xml(url: str, timeout: int = 10) -> etree._Element | None:
    """GETリクエストでXMLを取得しパースする。エラー時はNoneを返す。"""
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "bousai-dashboard/1.0"})
        resp.raise_for_status()
        return etree.fromstring(resp.content)
    except requests.exceptions.Timeout:
        logger.error("Timeout: %s", url)
    except requests.exceptions.HTTPError as e:
        logger.error("HTTP error %s: %s", e.response.status_code, url)
    except requests.exceptions.RequestException as e:
        logger.error("Request failed (%s): %s", e, url)
    except etree.XMLSyntaxError as e:
        logger.error("XML parse error (%s): %s", e, url)
    return None
