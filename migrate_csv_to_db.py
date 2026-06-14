#!/usr/bin/env python3
"""
一次性迁移脚本：将历史 CSV 数据导入 NeonDB。

用法：
  export DATABASE_URL='postgresql://user:pass@ep-xxx.neon.tech/dbname?sslmode=require'
  python migrate_csv_to_db.py
"""

import csv
import logging
from pathlib import Path

import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

CSV_DIR = Path(__file__).parent / "data" / "etf_shares_by_month"
CSV_HEADER = ["date", "exchange", "code", "name", "total_shares_wanfen"]


def read_csv_rows(csv_path: Path) -> list[dict]:
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                rows.append(
                    {
                        "date": row["date"],
                        "exchange": row["exchange"],
                        "code": row["code"],
                        "name": row["name"],
                        "total_shares_wanfen": float(row["total_shares_wanfen"])
                        if row["total_shares_wanfen"]
                        else None,
                    }
                )
            except (ValueError, KeyError) as exc:
                log.warning("Skipping row in %s: %s", csv_path.name, exc)
    return rows


def main():
    log.info("=== CSV -> NeonDB migration started ===")

    db.init_db()
    existing = db.load_existing_keys()
    log.info("Existing keys in database: %d", len(existing))

    csv_files = sorted(CSV_DIR.glob("etf_shares_*.csv"))
    if not csv_files:
        log.info("No CSV files found in %s", CSV_DIR)
        return

    total = 0
    skipped = 0
    for csv_path in csv_files:
        rows = read_csv_rows(csv_path)
        new_rows = [
            r for r in rows if (r["date"], r["exchange"], r["code"]) not in existing
        ]
        skipped += len(rows) - len(new_rows)
        if new_rows:
            db.upsert_shares(new_rows)
            total += len(new_rows)
            for r in new_rows:
                existing.add((r["date"], r["exchange"], r["code"]))
        log.info(
            "%s: %d rows total, %d new, %d skipped",
            csv_path.name,
            len(rows),
            len(new_rows),
            len(rows) - len(new_rows),
        )

    log.info(
        "=== Migration done. New: %d, Skipped (already exists): %d ===", total, skipped
    )


if __name__ == "__main__":
    main()
