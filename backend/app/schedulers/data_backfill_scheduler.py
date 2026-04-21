"""Data backfill scheduler.

Runs on startup and then every 10 minutes to detect and fill gaps.
Works alongside WebSocket and periodic schedulers.

Execution order:
  Phase 1: Funding history — OKX + Bybit  (no ban risk)
  Phase 2: Funding history — Binance       (moderate risk)
  Phase 3: Kline — 1d + 4h                 (important, few candles)
  Phase 4: Kline — 1h + 15m
  Phase 5: Kline — 5m                      (WS fills quickly, lowest priority)
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select, func
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.database import async_session_factory
from app.models.market_data import PriceKline, FundingHistory, FundingCap
from app.services.exchange.binance import BinanceClient
from app.services.funding_rank import FundingRankService, BINANCE, OKX, BYBIT

logger = logging.getLogger(__name__)

_UTC8 = timezone(timedelta(hours=8))

# ── Kline config ──
# retention_hours → how many candles we expect, and how far back to fetch
KLINE_INTERVALS = {
    "1d":  {"retention_hours": 4320, "candles": 180,  "limit": 180},
    "4h":  {"retention_hours": 720,  "candles": 180,  "limit": 180},
    "1h":  {"retention_hours": 168,  "candles": 168,  "limit": 168},
    "15m": {"retention_hours": 48,   "candles": 192,  "limit": 192},
    "5m":  {"retention_hours": 80,   "candles": 960,  "limit": 960},
}
KLINE_DENSITY_THRESHOLD = 0.7  # need at least 70% of expected candles

# ── Funding config ──
FUNDING_RETENTION_DAYS = 30

# ── Rate control ──
BATCH_SIZE = 20
BATCH_DELAY = 0.2         # seconds between batches
RATE_LIMIT_PAUSE = 300    # 5 minutes pause on 418
CHECK_INTERVAL = 600      # 10 minutes between periodic checks


class DataBackfillScheduler:
    """Periodic data integrity checker and backfiller.

    Runs immediately on startup, then every 10 minutes.
    Each run checks all data types for gaps and fills them.
    """

    def __init__(self) -> None:
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._check_in_progress = False

    def start_background(self) -> None:
        """Launch the periodic backfill loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._loop())

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()

    async def _loop(self) -> None:
        """Run backfill check on startup, then every CHECK_INTERVAL seconds."""
        try:
            while self._running:
                await self._run_once()
                # Wait for next check
                await asyncio.sleep(CHECK_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _run_once(self) -> None:
        """Execute one full backfill check across all data types."""
        if self._check_in_progress:
            return
        self._check_in_progress = True
        t0 = time.time()

        try:
            # Phase 1: Funding — OKX + Bybit (safe)
            await self._backfill_funding([OKX, BYBIT])

            # Phase 2: Funding — Binance
            await self._backfill_funding([BINANCE])

            # Phase 3: Kline — 1d + 4h
            await self._backfill_klines(["1d", "4h"])

            # Phase 4: Kline — 1h + 15m
            await self._backfill_klines(["1h", "15m"])

            # Phase 5: Kline — 5m
            await self._backfill_klines(["5m"])

            elapsed = time.time() - t0
            logger.info("Data backfill check done in %.0f seconds", elapsed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Data backfill check failed: %s", exc)
        finally:
            self._check_in_progress = False

    # ==================================================================
    # Kline backfill
    # ==================================================================

    async def _backfill_klines(self, intervals: list[str]) -> None:
        """Backfill kline data for given intervals."""
        # Get symbols
        symbols = await self._get_bn_symbols()
        if not symbols:
            logger.warning("Kline backfill: no symbols, skipping")
            return

        sem = asyncio.Semaphore(10)

        for interval in intervals:
            if not self._running:
                return

            cfg = KLINE_INTERVALS[interval]
            retention_hours = cfg["retention_hours"]
            expected = cfg["candles"]
            limit = cfg["limit"]
            min_count = int(expected * KLINE_DENSITY_THRESHOLD)

            # Check which symbols need backfill
            cutoff = datetime.now() - timedelta(hours=retention_hours)
            try:
                async with async_session_factory() as db:
                    result = await db.execute(
                        select(PriceKline.symbol, func.count().label("cnt"))
                        .where(PriceKline.interval_type == interval)
                        .where(PriceKline.kline_time >= cutoff)
                        .group_by(PriceKline.symbol)
                    )
                    counts = {row[0]: row[1] for row in result.all()}
            except Exception as exc:
                logger.error("Kline backfill [%s] check failed: %s", interval, exc)
                continue

            sparse = [s for s in symbols if counts.get(s, 0) < min_count]
            if not sparse:
                logger.info("Kline backfill [%s]: all %d symbols OK (>=%d candles)",
                            interval, len(symbols), min_count)
                continue

            logger.info("Kline backfill [%s]: %d/%d symbols sparse (need %d, limit=%d)",
                        interval, len(sparse), len(symbols), min_count, limit)

            filled = 0
            rate_limited = False

            async def fetch_one(client: BinanceClient, symbol: str, _interval: str, _limit: int) -> int:
                nonlocal rate_limited
                if rate_limited or not self._running:
                    return 0
                async with sem:
                    try:
                        klines = await client.get_klines(
                            symbol=symbol, interval=_interval, limit=_limit, timeout=15
                        )
                        if not klines:
                            return 0
                        # Batch insert — one statement for all candles
                        values = [
                            {
                                "symbol": symbol,
                                "interval_type": _interval,
                                "open_price": float(k[1]),
                                "high_price": float(k[2]),
                                "low_price": float(k[3]),
                                "close_price": float(k[4]),
                                "kline_time": datetime.fromtimestamp(int(k[0]) / 1000),
                            }
                            for k in klines
                        ]
                        async with async_session_factory() as db:
                            stmt = mysql_insert(PriceKline).values(values)
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
                            rate_limited = True
                            logger.warning("Kline backfill [%s]: rate limited, pausing %ds",
                                           _interval, RATE_LIMIT_PAUSE)
                        else:
                            logger.debug("Kline backfill [%s] %s failed: %s", _interval, symbol, exc)
                        return 0

            async with BinanceClient() as client:
                for i in range(0, len(sparse), BATCH_SIZE):
                    if not self._running:
                        return
                    if rate_limited:
                        # Pause then retry
                        logger.info("Kline backfill [%s]: waiting %ds after rate limit...",
                                    interval, RATE_LIMIT_PAUSE)
                        await asyncio.sleep(RATE_LIMIT_PAUSE)
                        rate_limited = False

                    batch = sparse[i:i + BATCH_SIZE]
                    tasks = [fetch_one(client, s, interval, limit) for s in batch]
                    results = await asyncio.gather(*tasks)
                    filled += sum(results)

                    progress = min(i + BATCH_SIZE, len(sparse))
                    if progress % 50 == 0 or progress == len(sparse):
                        logger.info("Kline backfill [%s]: %d/%d (filled %d records)",
                                    interval, progress, len(sparse), filled)

                    if i + BATCH_SIZE < len(sparse):
                        await asyncio.sleep(BATCH_DELAY)

            logger.info("Kline backfill [%s]: done — %d records", interval, filled)

    # ==================================================================
    # Funding history backfill
    # ==================================================================

    async def _backfill_funding(self, exchanges: list[str]) -> None:
        """Backfill funding history for given exchanges."""
        svc = FundingRankService()
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - FUNDING_RETENTION_DAYS * 24 * 3600 * 1000
        sem = asyncio.Semaphore(2)

        for exchange in exchanges:
            if not self._running:
                return

            # Get coins for this exchange
            try:
                coins = await svc._get_exchange_coins(exchange)
            except Exception as exc:
                logger.error("Funding backfill [%s]: failed to get coins: %s", exchange, exc)
                continue

            if not coins:
                logger.warning("Funding backfill [%s]: no coins found", exchange)
                continue

            # Check which coins are stale
            stale = await self._get_stale_funding_coins(exchange, coins)
            if not stale:
                logger.info("Funding backfill [%s]: all %d coins up to date", exchange, len(coins))
                continue

            logger.info("Funding backfill [%s]: %d/%d coins need backfill",
                        exchange, len(stale), len(coins))

            total_stored = 0
            failed = 0

            async def fetch_one(coin: str) -> Optional[tuple]:
                if not self._running:
                    return None
                async with sem:
                    try:
                        records = await svc._fetch_funding_for_exchange(
                            exchange, coin, start_ms, now_ms
                        )
                        await asyncio.sleep(0.3)
                        return (coin, records) if records else None
                    except Exception:
                        return None

            for i in range(0, len(stale), BATCH_SIZE):
                if not self._running:
                    return
                batch = stale[i:i + BATCH_SIZE]
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

                progress = min(i + BATCH_SIZE, len(stale))
                if progress % 50 == 0 or progress == len(stale):
                    logger.info("Funding backfill [%s]: %d/%d (stored %d)",
                                exchange, progress, len(stale), total_stored)

                if i + BATCH_SIZE < len(stale):
                    await asyncio.sleep(BATCH_DELAY)

            logger.info("Funding backfill [%s]: done — %d records, %d failed",
                        exchange, total_stored, failed)

    async def _get_stale_funding_coins(self, exchange: str, coins: set[str]) -> list[str]:
        """Find coins with stale or missing funding data."""
        # Load settlement periods from FundingCap
        exchange_map = {"BN": "Binance", "OKX": "OKX", "BY": "Bybit"}
        cap_exchange = exchange_map.get(exchange, exchange)

        coin_periods: dict[str, int] = {}
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(FundingCap.symbol, FundingCap.interval_hours)
                    .where(FundingCap.exchange == cap_exchange)
                )
                for row in result.all():
                    sym = row[0]
                    coin = sym[:-4] if sym.endswith("USDT") else sym.split("-")[0]
                    coin_periods[coin] = row[1] or 8
        except Exception:
            pass

        # Get latest funding_time per coin
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(FundingHistory.coin, func.max(FundingHistory.funding_time))
                    .where(FundingHistory.exchange == exchange)
                    .group_by(FundingHistory.coin)
                )
                latest_map = {row[0]: row[1] for row in result.all()}
        except Exception:
            latest_map = {}

        now = datetime.now()
        stale = []
        for coin in coins:
            latest = latest_map.get(coin)
            period = coin_periods.get(coin, 8)
            threshold = timedelta(hours=period, minutes=30)
            if latest is None or (now - latest) > threshold:
                stale.append(coin)
        return stale

    # ==================================================================
    # Helpers
    # ==================================================================

    async def _get_bn_symbols(self) -> list[str]:
        """Get Binance USDT perpetual symbols, with DB fallback."""
        try:
            async with BinanceClient() as client:
                info = await client.get_exchange_info()
            if info:
                return [
                    s["symbol"] for s in info.get("symbols", [])
                    if s.get("contractType") in ("PERPETUAL", "TRADIFI_PERPETUAL")
                    and s.get("quoteAsset") == "USDT"
                    and s.get("status") == "TRADING"
                ]
        except Exception:
            pass
        # Fallback
        try:
            async with async_session_factory() as db:
                result = await db.execute(select(PriceKline.symbol).distinct())
                return [row[0] for row in result.all()]
        except Exception:
            return []


# Singleton
data_backfill_scheduler = DataBackfillScheduler()
