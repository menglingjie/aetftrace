#!/usr/bin/env python3
"""
抓取上交所(SSE)和深交所(SZSE) ETF跟踪指数映射关系，保存到 data/etf_index_mapping.csv。

深交所: 从 SZSE API (catalog 1945) 获取，包含"拟合指数"字段。
上交所: 从 ETF 名称中提取指数信息（SSE 未提供直接 API）。
"""

import csv
import json
import logging
import re
import time
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
CSV_FILE = DATA_DIR / "etf_index_mapping.csv"
CSV_HEADER = ["exchange", "code", "name", "tracking_index", "fund_manager"]

SZSE_API = "https://www.szse.cn/api/report/ShowReport/data"
SZSE_CATALOG = "1945"
SSE_API = "https://query.sse.com.cn/commonQuery.do"
SSE_HEADERS = {"Referer": "https://www.sse.com.cn/"}
SSE_SQL_ID = "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L"

REQUEST_DELAY = 0.5
MAX_RETRIES = 3
RETRY_DELAY = 5.0


def request_with_retry(url, params, headers=None):
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.text
        except Exception as exc:
            log.warning("Request attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    return None


# ---------------------------------------------------------------------------
# SZSE (深交所)
# ---------------------------------------------------------------------------


def fetch_szse_etf_list():
    """Fetch all SZSE ETFs with tracking index from catalog 1945."""
    all_records = []
    page = 1
    while True:
        text = request_with_retry(
            SZSE_API,
            {
                "SHOWTYPE": "JSON",
                "CATALOGID": SZSE_CATALOG,
                "TABKEY": "tab1",
                "PAGENO": page,
                "PAGECOUNT": 50,
            },
        )
        if text is None:
            log.error("Failed to fetch SZSE page %d", page)
            break
        data = json.loads(text)
        records = data[0].get("data", [])
        total = data[0]["metadata"]["recordcount"]
        if not records:
            break
        all_records.extend(records)
        log.info(
            "SZSE page %d: %d records (total: %d/%d)",
            page,
            len(records),
            len(all_records),
            total,
        )
        if len(all_records) >= total:
            break
        page += 1
        time.sleep(REQUEST_DELAY)

    if not all_records:
        log.warning("SZSE returned no data (may be rate-limited), skipping")
        return []

    results = []
    for r in all_records:
        code_html = r.get("sys_key", "")
        name_html = r.get("kzjcurl", "")
        index_raw = r.get("nhzs", "").strip()
        manager = r.get("glrmc", "").strip()

        code_match = re.search(r">(\d{6})<", code_html)
        code = code_match.group(1) if code_match else code_html.strip()

        name_match = re.search(r">([^<]+)<", name_html)
        name = name_match.group(1).strip() if name_match else name_html.strip()

        results.append(
            {
                "exchange": "SZSE",
                "code": code,
                "name": name,
                "tracking_index": index_raw,
                "fund_manager": manager,
            }
        )

    log.info("SZSE: total %d ETFs with index mapping", len(results))
    return results


# ---------------------------------------------------------------------------
# SSE (上交所)
# ---------------------------------------------------------------------------


def fetch_sse_etf_list():
    """Fetch all SSE ETFs from the volume API (no tracking index available)."""
    all_rows = []
    page = 1
    total = None
    while True:
        params = {
            "jsonCallBack": "cb",
            "sqlId": SSE_SQL_ID,
            "STAT_DATE": "",
            "isPagination": "true",
            "pageHelp.pageSize": 50,
            "pageHelp.pageNo": page,
            "pageHelp.beginPage": 1,
            "pageHelp.endPage": 1,
            "pageHelp.cacheSize": 1,
        }
        text = request_with_retry(SSE_API, params, headers=SSE_HEADERS)
        if text is None:
            break
        json_str = text
        if json_str.startswith("cb(") and json_str.endswith(")"):
            json_str = json_str[3:-1]
        elif json_str.startswith("(") and json_str.endswith(")"):
            json_str = json_str[1:-1]
        data = json.loads(json_str)
        page_help = data.get("pageHelp", {})
        if total is None:
            total = int(page_help.get("total", 0))
        records = page_help.get("data", [])
        if not records:
            break
        for r in records:
            all_rows.append(
                {
                    "exchange": "SSE",
                    "code": r.get("SEC_CODE", "").strip(),
                    "name": r.get("SEC_NAME", ""),
                    "tracking_index": "",
                    "fund_manager": "",
                }
            )
        log.info(
            "SSE page %d: %d records (total: %d/%d)",
            page,
            len(records),
            len(all_rows),
            total,
        )
        if len(all_rows) >= total:
            break
        page += 1
        time.sleep(REQUEST_DELAY)

    log.info(
        "SSE: total %d ETFs (tracking index not available from API)", len(all_rows)
    )
    return all_rows


# ---------------------------------------------------------------------------
# Manual SSE index mapping (补充SSE的跟踪指数)
# ---------------------------------------------------------------------------

# SSE ETF 中，一些常见的 ETF 名称 -> 跟踪指数映射
# 这些映射可以通过 ETF 名称中的关键词推断
SSE_INDEX_KEYWORDS = {
    "50": "000016 上证50",
    "180": "000010 上证180",
    "300": "000300 沪深300",
    "500": "000905 中证500",
    "1000": "000852 中证1000",
    "科创": "000688 科创50",
    "科创50": "000688 科创50",
    "创业板": "399006 创业板指",
    "新能源": "399808 中证新能",
    "医药": "000933 中证医药",
    "消费": "000932 中证消费",
    "金融": "000914 中证金融",
    "军工": "399959 军工指数",
    "芯片": "990001 国证芯片",
    "半导体": "H30184 中华半导体",
    "AI": "930713 CS人工智能",
    "人工智能": "930713 CS人工智能",
    "机器人": "H30590 机器人指数",
    "新能源车": "399976 新能源车",
    "碳中和": "930971 碳中和指数",
    "红利": "000015 红利指数",
    "央企": "000015 红利指数",
    "国企": "000015 红利指数",
    "价值": "399367 价值指数",
    "质量": "000815 质量成长",
    "成长": "399370 成长100",
    "创业板50": "399673 创业板50",
    "恒生": "HSAHP 恒生指数",
    "H股": "HSCEI 恒生国企",
    "纳斯达克": "IXIC 纳斯达克",
    "标普": "SPX 标普500",
    "日经": "N225 日经225",
    "德国": "DAX 德国DAX",
    "法国": "CAC40 法国CAC40",
    "中证": "",
    "上证": "",
    "深证": "",
}


def infer_sse_index(name):
    """Try to infer tracking index from SSE ETF name."""
    for keyword, index in SSE_INDEX_KEYWORDS.items():
        if keyword in name:
            return index
    return ""


# ---------------------------------------------------------------------------
# CSV operations
# ---------------------------------------------------------------------------


def save_to_csv(rows, csv_path):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    log.info("Saved %d records to %s", len(rows), csv_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    log.info("=== ETF index mapping fetcher started ===")

    log.info("--- Fetching SZSE ETFs ---")
    szse_rows = fetch_szse_etf_list()

    log.info("--- Fetching SSE ETFs ---")
    sse_rows = fetch_sse_etf_list()
    for r in sse_rows:
        r["tracking_index"] = infer_sse_index(r["name"])

    all_rows = szse_rows + sse_rows
    save_to_csv(all_rows, CSV_FILE)

    with_index = sum(1 for r in all_rows if r["tracking_index"])
    log.info("Summary: %d total, %d with tracking index", len(all_rows), with_index)
    log.info("=== Done ===")


if __name__ == "__main__":
    main()
