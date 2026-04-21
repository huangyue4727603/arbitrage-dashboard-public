"""Backfill funding history + kline data from local machine to remote DB.

Covers:
  1. Funding history (BN / OKX / BY) — 7 days
  2. Price klines (all 5 intervals from Binance) — per-interval retention

Usage:
  cd backend
  EXCHANGE_PROXY=http://127.0.0.1:10080 python3 scripts/backfill_all_local.py
"""
import asyncio
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

from sqlalchemy import select, func
from sqlalchemy.dialects.mysql import insert as mysql_insert
from app.database import async_session_factory
from app.models.market_data import PriceKline, FundingHistory
from app.services.exchange.binance import BinanceClient
from app.services.exchange.okx import OKXClient
from app.services.exchange.bybit import BybitClient
from app.services.funding_rank import (
    FundingRankService, BINANCE, OKX, BYBIT,
    _to_bn_symbol, _to_okx_inst_id, _to_bybit_symbol,
)

_UTC8 = timezone(timedelta(hours=8))

# ── Kline config ──
KLINE_INTERVALS = {
    "5m":  {"limit": 320,  "retention_hours": 80},
    "15m": {"limit": 130,  "retention_hours": 48},
    "1h":  {"limit": 48,   "retention_hours": 168},
    "4h":  {"limit": 130,  "retention_hours": 720},
    "1d":  {"limit": 180,  "retention_hours": 4320},
}

KLINE_MIN_COUNTS = {"5m": 218, "15m": 89, "1h": 21, "4h": 88, "1d": 2}

# ── Funding config ──
FUNDING_DAYS = 7


# ===================== KLINE BACKFILL =====================

async def get_bn_symbols() -> list[str]:
    """Get all Binance USDT perpetual symbols."""
    async with BinanceClient() as client:
        info = await client.get_exchange_info()
    symbols = [
        s["symbol"] for s in (info or {}).get("symbols", [])
        if s.get("contractType") in ("PERPETUAL", "TRADIFI_PERPETUAL")
        and s.get("quoteAsset") == "USDT"
        and s.get("status") == "TRADING"
    ]
    logger.info("Binance: %d USDT perpetual symbols", len(symbols))
    return symbols


async def get_sparse_symbols(symbols: list[str], interval: str) -> list[str]:
    min_count = KLINE_MIN_COUNTS.get(interval, 1)
    required_hours = {"5m": 26, "1d": 96, "1h": 30, "15m": 32, "4h": 504}.get(interval, 24)
    cutoff = datetime.now() - timedelta(hours=required_hours)

    async with async_session_factory() as db:
        result = await db.execute(
            select(PriceKline.symbol, func.count().label("cnt"))
            .where(PriceKline.interval_type == interval)
            .where(PriceKline.kline_time >= cutoff)
            .group_by(PriceKline.symbol)
        )
        counts = {row[0]: row[1] for row in result.all()}

    sparse = [s for s in symbols if counts.get(s, 0) < min_count]
    return sparse


async def backfill_kline_symbol(client: BinanceClient, symbol: str, interval: str, limit: int) -> int:
    try:
        klines = await client.get_klines(symbol=symbol, interval=interval, limit=limit, timeout=15)
        if not klines:
            return 0

        async with async_session_factory() as db:
            for k in klines:
                kline_time = datetime.fromtimestamp(int(k[0]) / 1000)
                stmt = mysql_insert(PriceKline).values(
                    symbol=symbol,
                    interval_type=interval,
                    open_price=float(k[1]),
                    high_price=float(k[2]),
                    low_price=float(k[3]),
                    close_price=float(k[4]),
                    kline_time=kline_time,
                )
                stmt = stmt.on_duplicate_key_update(
                    open_price=stmt.inserted.open_price,
                    high_price=stmt.inserted.high_price,
                    low_price=stmt.inserted.low_price,
                    close_price=stmt.inserted.close_price,
                )
                await db.execute(stmt)
            await db.commit()
        return len(klines)
    except Exception as exc:
        if "418" in str(exc) or "429" in str(exc):
            logger.warning("Binance rate limited! Stopping kline backfill.")
            raise
        logger.debug("Kline failed %s %s: %s", symbol, interval, exc)
        return 0


async def backfill_klines(symbols: list[str]):
    logger.info("=" * 60)
    logger.info("KLINE BACKFILL START")
    logger.info("=" * 60)

    for interval, cfg in KLINE_INTERVALS.items():
        limit = cfg["limit"]
        sparse = await get_sparse_symbols(symbols, interval)

        if not sparse:
            logger.info("[kline %s] All symbols OK, skipping", interval)
            continue

        logger.info("[kline %s] Need to backfill %d/%d symbols (limit=%d)",
                     interval, len(sparse), len(symbols), limit)

        success = 0
        total_records = 0
        async with BinanceClient() as client:
            for i, symbol in enumerate(sparse):
                try:
                    count = await backfill_kline_symbol(client, symbol, interval, limit)
                    if count > 0:
                        success += 1
                        total_records += count
                    await asyncio.sleep(1)

                    if (i + 1) % 50 == 0:
                        logger.info("[kline %s] Progress: %d/%d (ok: %d, records: %d)",
                                    interval, i + 1, len(sparse), success, total_records)
                except Exception:
                    logger.warning("[kline %s] Stopped at %d/%d (rate limit)",
                                   interval, i + 1, len(sparse))
                    break

        logger.info("[kline %s] Done: %d/%d ok, %d records", interval, success, len(sparse), total_records)


# ===================== FUNDING BACKFILL =====================

async def get_exchange_coins() -> dict[str, set[str]]:
    """Get coin sets for each exchange."""
    svc = FundingRankService()
    bn, okx, bybit = await asyncio.gather(
        svc._get_exchange_coins(BINANCE),
        svc._get_exchange_coins(OKX),
        svc._get_exchange_coins(BYBIT),
    )
    logger.info("Exchange coins: BN=%d, OKX=%d, BY=%d", len(bn), len(okx), len(bybit))
    return {BINANCE: bn, OKX: okx, BYBIT: bybit}


async def get_stale_funding_coins(exchange: str, coins: set[str], days: int) -> list[str]:
    """Find coins with no funding data in the recent window."""
    cutoff = datetime.now() - timedelta(days=days)

    async with async_session_factory() as db:
        result = await db.execute(
            select(FundingHistory.coin, func.max(FundingHistory.funding_time))
            .where(FundingHistory.exchange == exchange)
            .where(FundingHistory.coin.in_(list(coins)))
            .group_by(FundingHistory.coin)
        )
        latest_map = {row[0]: row[1] for row in result.all()}

    stale = []
    # 2 hours threshold — if latest record is older than 2h, backfill
    threshold = datetime.now() - timedelta(hours=2)
    for coin in coins:
        latest = latest_map.get(coin)
        if latest is None or latest < threshold:
            stale.append(coin)
    return stale


async def backfill_funding():
    logger.info("=" * 60)
    logger.info("FUNDING BACKFILL START (%d days)", FUNDING_DAYS)
    logger.info("=" * 60)

    exchange_coins = await get_exchange_coins()
    svc = FundingRankService()
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - FUNDING_DAYS * 24 * 3600 * 1000
    sem = asyncio.Semaphore(2)

    for exchange, coins in exchange_coins.items():
        stale = await get_stale_funding_coins(exchange, coins, FUNDING_DAYS)
        if not stale:
            logger.info("[funding %s] All coins up to date, skipping", exchange)
            continue

        logger.info("[funding %s] Need to backfill %d/%d coins", exchange, len(stale), len(coins))

        total_stored = 0
        failed = 0

        async def fetch_one(coin: str):
            async with sem:
                try:
                    records = await svc._fetch_funding_for_exchange(exchange, coin, start_ms, now_ms)
                    await asyncio.sleep(0.3)
                    return (coin, records) if records else None
                except Exception as exc:
                    logger.debug("Funding fetch failed %s/%s: %s", exchange, coin, exc)
                    return None

        # Process in batches of 10
        for i in range(0, len(stale), 10):
            batch = stale[i:i + 10]
            tasks = [fetch_one(coin) for coin in batch]
            results = await asyncio.gather(*tasks)

            async with async_session_factory() as db:
                for r in results:
                    if r is None:
                        failed += 1
                        continue
                    coin, records = r
                    if not records:
                        continue
                    values = [
                        {
                            "exchange": exchange,
                            "coin": coin,
                            "funding_rate": rec["rate"],
                            "funding_time": datetime.fromtimestamp(
                                rec["time_ms"] / 1000, tz=_UTC8
                            ).replace(tzinfo=None),
                        }
                        for rec in records
                    ]
                    stmt = mysql_insert(FundingHistory).values(values)
                    stmt = stmt.on_duplicate_key_update(
                        funding_rate=stmt.inserted.funding_rate,
                    )
                    await db.execute(stmt)
                    total_stored += len(values)
                await db.commit()

            progress = min(i + 10, len(stale))
            logger.info("[funding %s] Progress: %d/%d (stored: %d)",
                        exchange, progress, len(stale), total_stored)

            if i + 10 < len(stale):
                await asyncio.sleep(1)

        logger.info("[funding %s] Done: %d records stored, %d failed",
                    exchange, total_stored, failed)


# ===================== MAIN =====================

async def main():
    t0 = time.time()

    # Phase 1: Funding history (uses all 3 exchange APIs)
    await backfill_funding()

    # Phase 2: Kline data (Binance only)
    symbols = await get_bn_symbols()
    if symbols:
        await backfill_klines(symbols)

    elapsed = time.time() - t0
    logger.info("=" * 60)
    logger.info("ALL BACKFILL COMPLETE in %.0f seconds", elapsed)
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
