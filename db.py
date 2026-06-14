#!/usr/bin/env python3
"""
PostgreSQL 数据库操作模块（NeonDB）。

通过 DATABASE_URL 环境变量连接数据库。
表结构与 CSV 的 etf_shares 字段一一对应。
"""

import logging
import os

import psycopg2
import psycopg2.extras

log = logging.getLogger(__name__)

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS etf_shares (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    exchange VARCHAR(4) NOT NULL,
    code VARCHAR(10) NOT NULL,
    name VARCHAR(50),
    total_shares_wanfen NUMERIC(15, 2),
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(trade_date, exchange, code)
);
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_etf_shares_date ON etf_shares(trade_date);
"""

UPSERT_SQL = """
INSERT INTO etf_shares (trade_date, exchange, code, name, total_shares_wanfen)
VALUES (%(date)s, %(exchange)s, %(code)s, %(name)s, %(total_shares_wanfen)s)
ON CONFLICT (trade_date, exchange, code)
DO UPDATE SET
    name = EXCLUDED.name,
    total_shares_wanfen = EXCLUDED.total_shares_wanfen;
"""

SELECT_KEYS_SQL = "SELECT trade_date, exchange, code FROM etf_shares"

BATCH_SIZE = 500


def _get_dsn() -> str | None:
    return os.environ.get("DATABASE_URL")


def get_connection():
    dsn = _get_dsn()
    if not dsn:
        raise RuntimeError(
            "DATABASE_URL 环境变量未设置。"
            "请设置 NeonDB 连接字符串，例如：\n"
            "  export DATABASE_URL='postgresql://user:pass@ep-xxx.neon.tech/dbname?sslmode=require'"
        )
    return psycopg2.connect(dsn)


def init_db():
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
            cur.execute(CREATE_INDEX_SQL)
        conn.commit()
        log.info("Database table etf_shares ready")
    finally:
        conn.close()


def load_existing_keys() -> set[tuple[str, str, str]]:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(SELECT_KEYS_SQL)
            keys = set()
            for row in cur:
                date_str = (
                    row[0].strftime("%Y-%m-%d")
                    if hasattr(row[0], "strftime")
                    else str(row[0])
                )
                keys.add((date_str, row[1], row[2]))
            return keys
    finally:
        conn.close()


def upsert_shares(rows: list[dict]) -> int:
    if not rows:
        return 0
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            inserted = 0
            for i in range(0, len(rows), BATCH_SIZE):
                batch = rows[i : i + BATCH_SIZE]
                psycopg2.extras.execute_batch(
                    cur, UPSERT_SQL, batch, page_size=BATCH_SIZE
                )
                inserted += len(batch)
            conn.commit()
            log.info("Upserted %d records to database", inserted)
            return inserted
    finally:
        conn.close()
