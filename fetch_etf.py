#!/usr/bin/env python3
"""
每日抓取上交所(SSE)和深交所(SZSE) ETF份额数据，追加写入 CSV 文件。

首次运行时自动回抓最近 1 个月历史数据，后续每日只抓当天增量。
"""

import csv
import json
import logging
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"
CSV_DIR = DATA_DIR / "etf_shares_by_month"
CSV_HEADER = ["date", "exchange", "code", "name", "total_shares_wanfen"]


def get_csv_path(date_str: str) -> Path:
    """根据日期获取对应的月份CSV文件路径"""
    month_key = date_str[:7]  # YYYY-MM
    return CSV_DIR / f"etf_shares_{month_key}.csv"


SSE_API = "https://query.sse.com.cn/commonQuery.do"
SSE_HEADERS = {"Referer": "https://www.sse.com.cn/"}
SSE_SQL_ID = "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L"
SSE_PAGE_SIZE = 50

SZSE_API = "https://www.szse.cn/api/report/ShowReport/data"
SZSE_CATALOG = "scsj_fund_jjgm"
SZSE_PAGE_SIZE = 50

REQUEST_DELAY = 1.0
MAX_RETRIES = 3
RETRY_DELAY = 5.0
HISTORY_DAYS = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def today_str() -> str:
    return date.today().strftime("%Y-%m-%d")


def date_range(start: str, end: str) -> list[str]:
    """Return list of date strings from start to end inclusive."""
    d0 = datetime.strptime(start, "%Y-%m-%d").date()
    d1 = datetime.strptime(end, "%Y-%m-%d").date()
    return [
        (d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range((d1 - d0).days + 1)
    ]


def request_with_retry(
    url: str, params: dict, headers: dict | None = None
) -> str | None:
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
# SSE (上交所)
# ---------------------------------------------------------------------------


def fetch_sse_page(stat_date: str, page_no: int) -> tuple[list[dict], int]:
    params = {
        "jsonCallBack": "cb",
        "sqlId": SSE_SQL_ID,
        "STAT_DATE": stat_date,
        "isPagination": "true",
        "pageHelp.pageSize": SSE_PAGE_SIZE,
        "pageHelp.pageNo": page_no,
        "pageHelp.beginPage": 1,
        "pageHelp.endPage": 1,
        "pageHelp.cacheSize": 1,
    }
    text = request_with_retry(SSE_API, params, headers=SSE_HEADERS)
    if text is None:
        return [], 0
    try:
        json_str = text
        if json_str.startswith("cb(") and json_str.endswith(")"):
            json_str = json_str[3:-1]
        elif json_str.startswith("(") and json_str.endswith(")"):
            json_str = json_str[1:-1]
        data = json.loads(json_str)
        page_help = data.get("pageHelp", {})
        total = int(page_help.get("total", 0))
        records = page_help.get("data", [])
        rows = []
        for r in records:
            rows.append(
                {
                    "date": r.get("STAT_DATE", ""),
                    "exchange": "SSE",
                    "code": r.get("SEC_CODE", "").strip(),
                    "name": r.get("SEC_NAME", ""),
                    "total_shares_wanfen": r.get("TOT_VOL", ""),
                }
            )
        return rows, total
    except Exception as exc:
        log.error(
            "Failed to parse SSE response for %s page %d: %s", stat_date, page_no, exc
        )
        return [], 0


def fetch_sse_date(stat_date: str) -> list[dict]:
    all_rows, total = fetch_sse_page(stat_date, 1)
    if total == 0 and not all_rows:
        return []
    total_pages = (total + SSE_PAGE_SIZE - 1) // SSE_PAGE_SIZE
    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_DELAY)
        rows, _ = fetch_sse_page(stat_date, page)
        all_rows.extend(rows)
    log.info("SSE %s: %d records (%d pages)", stat_date, len(all_rows), total_pages)
    return all_rows


# ---------------------------------------------------------------------------
# SZSE (深交所)
# ---------------------------------------------------------------------------


def fetch_szse_page(
    start_date: str, end_date: str, page_no: int
) -> tuple[list[dict], int]:
    params = {
        "SHOWTYPE": "JSON",
        "CATALOGID": SZSE_CATALOG,
        "jjlb": "ETF",
        "PAGENO": page_no,
        "PAGECOUNT": SZSE_PAGE_SIZE,
        "txtStart": start_date,
        "txtEnd": end_date,
    }
    text = request_with_retry(SZSE_API, params)
    if text is None:
        return [], 0
    try:
        data = json.loads(text)
        if not isinstance(data, list) or len(data) == 0:
            return [], 0
        meta = data[0].get("metadata", {})
        total = int(meta.get("recordcount", 0))
        records = data[0].get("data", [])
        rows = []
        for r in records:
            raw_date = r.get("size_date", "")
            raw_code = r.get("fund_code", "").strip()
            raw_name = r.get("security_short_name", "")
            raw_size = r.get("current_size", "").replace(",", "")
            rows.append(
                {
                    "date": raw_date,
                    "exchange": "SZSE",
                    "code": raw_code,
                    "name": raw_name,
                    "total_shares_wanfen": raw_size,
                }
            )
        return rows, total
    except Exception as exc:
        log.error("Failed to parse SZSE response: %s", exc)
        return [], 0


def fetch_szse_date(stat_date: str) -> list[dict]:
    all_rows, total = fetch_szse_page(stat_date, stat_date, 1)
    if total == 0 and not all_rows:
        return []
    total_pages = (total + SZSE_PAGE_SIZE - 1) // SZSE_PAGE_SIZE
    for page in range(2, total_pages + 1):
        time.sleep(REQUEST_DELAY)
        rows, _ = fetch_szse_page(stat_date, stat_date, page)
        all_rows.extend(rows)
    log.info("SZSE %s: %d records (%d pages)", stat_date, len(all_rows), total_pages)
    return all_rows


# ---------------------------------------------------------------------------
# CSV operations
# ---------------------------------------------------------------------------


def load_existing_keys(csv_path: Path) -> set[tuple[str, str, str]]:
    keys = set()
    if not csv_path.exists():
        return keys
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keys.add((row["date"], row["exchange"], row["code"]))
    return keys


def load_all_existing_keys() -> tuple[set[tuple[str, str, str]], dict[str, Path]]:
    """加载所有月份文件的已有key，返回 (keys, month_to_path)"""
    keys: set[tuple[str, str, str]] = set()
    month_to_path: dict[str, Path] = {}
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    for f in CSV_DIR.glob("etf_shares_*.csv"):
        month_key = f.stem.replace("etf_shares_", "")
        month_to_path[month_key] = f
        keys |= load_existing_keys(f)
    return keys, month_to_path


def append_to_csv(
    csv_path: Path, rows: list[dict], existing: set[tuple[str, str, str]]
):
    if not rows:
        return 0
    new_rows = [
        r for r in rows if (r["date"], r["exchange"], r["code"]) not in existing
    ]
    if not new_rows:
        return 0
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not csv_path.exists() or csv_path.stat().st_size == 0
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        if write_header:
            writer.writeheader()
        for r in new_rows:
            writer.writerow(r)
            existing.add((r["date"], r["exchange"], r["code"]))
    return len(new_rows)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def determine_dates(existing: set[tuple[str, str, str]]) -> list[str]:
    today = today_str()
    if not existing:
        start = (date.today() - timedelta(days=HISTORY_DAYS)).strftime("%Y-%m-%d")
        log.info("No existing data, backfilling from %s to %s", start, today)
        return date_range(start, today)
    existing_dates = sorted({k[0] for k in existing})
    latest = existing_dates[-1]
    if latest >= today:
        log.info("Data for %s already exists, nothing to do", today)
        return []
    start = (datetime.strptime(latest, "%Y-%m-%d").date() + timedelta(days=1)).strftime(
        "%Y-%m-%d"
    )
    log.info("Resuming from %s to %s (latest existing: %s)", start, today, latest)
    return date_range(start, today)


def main():
    log.info("=== ETF share fetcher started ===")
    existing, _ = load_all_existing_keys()
    dates = determine_dates(existing)
    if not dates:
        log.info("Nothing to fetch, exiting")
        return

    total_added = 0

    for d in dates:
        log.info("--- Fetching date: %s ---", d)
        time.sleep(REQUEST_DELAY)
        sse_rows = fetch_sse_date(d)
        time.sleep(REQUEST_DELAY)
        szse_rows = fetch_szse_date(d)
        all_rows = sse_rows + szse_rows
        csv_path = get_csv_path(d)
        added = append_to_csv(csv_path, all_rows, existing)
        total_added += added
        log.info(
            "%s: added %d new records (SSE=%d, SZSE=%d)",
            d,
            added,
            len(sse_rows),
            len(szse_rows),
        )

    log.info("=== Done. Total added: %d records ===", total_added)


if __name__ == "__main__":
    main()
