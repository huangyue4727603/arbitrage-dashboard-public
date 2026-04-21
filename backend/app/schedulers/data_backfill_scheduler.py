"""Data backfill & health monitor scheduler.

Responsibilities:
  1. Periodic data integrity check + gap fill (every 10 min)
  2. WebSocket health monitoring (every 60s)
  3. Data freshness watchdog (every 60s)
  4. All Binance REST calls use raw aiohttp to bypass BinanceClient cooldown

Kline backfill bypasses BinanceClient entirely — uses direct HTTP to
avoid being blocked by per-group cooldowns from other modules.
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import aiohttp
from sqlalchemy import select, func
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.database import async_session_factory
from app.models.market_data import PriceKline, FundingHistory, FundingCap, BnSpotSymbol
from app.services.funding_rank import FundingRankService, BINANCE, OKX, BYBIT

logger = logging.getLogger(__name__)

_UTC8 = timezone(timedelta(hours=8))
BN_API = "https://fapi.binance.com"

# ── Kline config ──
KLINE_INTERVALS = {
    "1d":  {"retention_hours": 4320, "candles": 180,  "limit": 180},
    "4h":  {"retention_hours": 720,  "candles": 180,  "limit": 180},
    "1h":  {"retention_hours": 168,  "candles": 168,  "limit": 168},
    "15m": {"retention_hours": 48,   "candles": 192,  "limit": 192},
    "5m":  {"retention_hours": 80,   "candles": 960,  "limit": 960},
}
KLINE_DENSITY_THRESHOLD = 0.7

# ── Funding config ──
FUNDING_RETENTION_DAYS = 30

# ── Rate control ──
BATCH_SIZE = 20
BATCH_DELAY = 0.2
RATE_LIMIT_PAUSE = 300
CHECK_INTERVAL = 600       # 10 min between backfill checks
HEALTH_INTERVAL = 60       # 60s between health checks

# ── Freshness thresholds (seconds) — warn if data older than this ──
FRESHNESS_THRESHOLDS = {
    "kline_5m": 600,        # 10 min (2 candle periods)
    "kline_15m": 1800,      # 30 min
    "kline_1h": 7200,       # 2 hours
    "funding_BN": 3600 * 9, # 9 hours (8h period + buffer)
    "funding_OKX": 3600 * 9,
    "funding_BY": 3600 * 9,
    "realtime": 30,         # 30 seconds
}


class DataBackfillScheduler:
    """Periodic data integrity checker, backfiller, and health monitor."""

    def __init__(self) -> None:
        self._running = False
        self._backfill_task: Optional[asyncio.Task] = None
        self._health_task: Optional[asyncio.Task] = None
        self._check_in_progress = False
        # Track WS health
        self._last_ws_kline_time: float = 0.0
        self._ws_healthy = True
        # BN spot symbols — refresh once per day
        self._bn_spot_last_refresh: float = 0.0

    def start_background(self) -> None:
        if self._running:
            return
        self._running = True
        self._backfill_task = asyncio.ensure_future(self._backfill_loop())
        self._health_task = asyncio.ensure_future(self._health_loop())

    def stop(self) -> None:
        self._running = False
        for task in [self._backfill_task, self._health_task]:
            if task:
                task.cancel()

    # ==================================================================
    # Health monitor loop (every 60s)
    # ==================================================================

    async def _health_loop(self) -> None:
        """Monitor WS health and data freshness."""
        try:
            await asyncio.sleep(120)  # wait 2 min for startup
            while self._running:
                await self._check_ws_health()
                await self._check_data_freshness()
                await asyncio.sleep(HEALTH_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _check_ws_health(self) -> None:
        """Check if Binance kline WS is producing data."""
        from app.services.binance_kline_ws import binance_kline_ws
        current_stored = binance_kline_ws._total_stored

        if self._last_ws_kline_time == 0:
            # First check — just record baseline
            self._last_ws_kline_time = time.time()
            self._ws_healthy = True
            return

        # If no new klines in 10 minutes, WS is likely dead
        elapsed = time.time() - self._last_ws_kline_time
        if current_stored > getattr(self, '_last_ws_count', 0):
            # WS produced data — healthy
            self._last_ws_kline_time = time.time()
            self._last_ws_count = current_stored
            if not self._ws_healthy:
                logger.info("WS health: Binance kline WS recovered")
                self._ws_healthy = True
        elif elapsed > 600:
            # No new data in 10 min
            if self._ws_healthy:
                logger.warning("WS health: Binance kline WS appears down (no data for %.0fs), "
                               "backfill will compensate", elapsed)
                self._ws_healthy = False

    async def _check_data_freshness(self) -> None:
        """Check if each data type is fresh enough, log warnings."""
        try:
            async with async_session_factory() as db:
                now = datetime.now()
                warnings = []

                # Kline freshness (check 5m, 15m, 1h)
                for interval, threshold_key in [("5m", "kline_5m"), ("15m", "kline_15m"), ("1h", "kline_1h")]:
                    r = await db.execute(
                        select(func.max(PriceKline.kline_time))
                        .where(PriceKline.interval_type == interval)
                    )
                    latest = r.scalar()
                    if latest:
                        age = (now - latest).total_seconds()
                        threshold = FRESHNESS_THRESHOLDS[threshold_key]
                        if age > threshold:
                            warnings.append("kline_%s stale (%.0fmin old)" % (interval, age / 60))

                # Funding freshness per exchange
                for exchange in ["BN", "OKX", "BY"]:
                    r = await db.execute(
                        select(func.max(FundingHistory.funding_time))
                        .where(FundingHistory.exchange == exchange)
                    )
                    latest = r.scalar()
                    if latest:
                        age = (now - latest).total_seconds()
                        threshold = FRESHNESS_THRESHOLDS.get("funding_" + exchange, 3600 * 9)
                        if age > threshold:
                            warnings.append("funding_%s stale (%.0fh old)" % (exchange, age / 3600))

                # Realtime data freshness
                from app.services.data_fetcher import data_fetcher
                cached = data_fetcher.get_cached_data()
                if not cached or all(not v for v in cached.values()):
                    warnings.append("realtime data empty")

                if warnings:
                    logger.warning("Data freshness: %s", "; ".join(warnings))
        except Exception as exc:
            logger.error("Freshness check failed: %s", exc)

    # ==================================================================
    # Backfill loop (every 10 min)
    # ==================================================================

    async def _backfill_loop(self) -> None:
        try:
            while self._running:
                await self._run_once()
                await asyncio.sleep(CHECK_INTERVAL)
        except asyncio.CancelledError:
            pass

    async def _run_once(self) -> None:
        if self._check_in_progress:
            return
        self._check_in_progress = True
        t0 = time.time()

        try:
            await self._refresh_bn_spot_symbols()
            await self._backfill_funding([OKX, BYBIT])
            await self._backfill_funding([BINANCE])
            await self._backfill_klines(["1d", "4h"])
            await self._backfill_klines(["1h", "15m"])
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
    # Kline backfill — raw aiohttp, bypasses BinanceClient cooldown
    # ==================================================================

    async def _backfill_klines(self, intervals: list[str]) -> None:
        symbols = await self._get_bn_symbols()
        if not symbols:
            return

        sem = asyncio.Semaphore(10)
        timeout = aiohttp.ClientTimeout(total=15)

        for interval in intervals:
            if not self._running:
                return

            cfg = KLINE_INTERVALS[interval]
            min_count = int(cfg["candles"] * KLINE_DENSITY_THRESHOLD)
            limit = cfg["limit"]

            cutoff = datetime.now() - timedelta(hours=cfg["retention_hours"])
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
                continue

            logger.info("Kline backfill [%s]: %d/%d sparse (need %d)",
                        interval, len(sparse), len(symbols), min_count)

            filled = 0
            rate_limited = False

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async def fetch_one(symbol: str, _interval: str, _limit: int) -> int:
                    nonlocal rate_limited
                    if rate_limited or not self._running:
                        return 0
                    async with sem:
                        try:
                            params = {"symbol": symbol, "interval": _interval, "limit": _limit}
                            async with session.get(f"{BN_API}/fapi/v1/klines", params=params) as resp:
                                if resp.status in (418, 429):
                                    rate_limited = True
                                    logger.warning("Kline backfill [%s]: rate limited", _interval)
                                    return 0
                                if resp.status != 200:
                                    return 0
                                klines = await resp.json()
                            if not klines:
                                return 0
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
                            return 0

                for i in range(0, len(sparse), BATCH_SIZE):
                    if not self._running:
                        return
                    if rate_limited:
                        logger.info("Kline backfill [%s]: pausing %ds after rate limit",
                                    interval, RATE_LIMIT_PAUSE)
                        await asyncio.sleep(RATE_LIMIT_PAUSE)
                        rate_limited = False

                    batch = sparse[i:i + BATCH_SIZE]
                    tasks = [fetch_one(s, interval, limit) for s in batch]
                    results = await asyncio.gather(*tasks)
                    filled += sum(results)

                    progress = min(i + BATCH_SIZE, len(sparse))
                    if progress % 50 == 0 or progress == len(sparse):
                        logger.info("Kline backfill [%s]: %d/%d (filled %d)",
                                    interval, progress, len(sparse), filled)
                    if i + BATCH_SIZE < len(sparse):
                        await asyncio.sleep(BATCH_DELAY)

            if filled > 0:
                logger.info("Kline backfill [%s]: done — %d records", interval, filled)

    # ==================================================================
    # Funding backfill — also raw aiohttp for Binance
    # ==================================================================

    async def _backfill_funding(self, exchanges: list[str]) -> None:
        svc = FundingRankService()
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - FUNDING_RETENTION_DAYS * 24 * 3600 * 1000
        sem = asyncio.Semaphore(5)
        timeout = aiohttp.ClientTimeout(total=30)

        for exchange in exchanges:
            if not self._running:
                return

            # Get coins — try API first, always fall back to DB
            try:
                coins = await svc._get_exchange_coins(exchange)
            except Exception:
                coins = set()
            if not coins:
                # DB fallback — always available even when API is down
                coins = await svc._get_exchange_coins_from_db(exchange)
                if coins:
                    logger.info("Funding backfill [%s]: using DB fallback (%d coins)",
                                exchange, len(coins))
            if not coins:
                continue

            stale = await self._get_stale_funding_coins(exchange, coins)
            if not stale:
                continue

            logger.info("Funding backfill [%s]: %d/%d stale", exchange, len(stale), len(coins))

            total_stored = 0

            if exchange == BINANCE:
                # Raw aiohttp — bypass BinanceClient cooldown
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async def fetch_bn(coin: str):
                        async with sem:
                            symbol = coin + "USDT"
                            all_records = []
                            current_start = start_ms
                            while current_start < now_ms:
                                params = {"symbol": symbol, "startTime": current_start,
                                          "endTime": now_ms, "limit": 1000}
                                try:
                                    async with session.get(
                                        f"{BN_API}/fapi/v1/fundingRate", params=params
                                    ) as resp:
                                        if resp.status in (418, 429):
                                            return None
                                        if resp.status != 200:
                                            break
                                        records = await resp.json()
                                except Exception:
                                    break
                                if not records:
                                    break
                                all_records.extend(records)
                                last_t = int(records[-1].get("fundingTime", 0))
                                if last_t <= current_start or len(records) < 1000:
                                    break
                                current_start = last_t + 1
                            await asyncio.sleep(0.2)
                            if not all_records:
                                return None
                            return (coin, [
                                {"time_ms": int(r["fundingTime"]), "rate": float(r["fundingRate"])}
                                for r in all_records
                            ])

                    for i in range(0, len(stale), BATCH_SIZE):
                        batch = stale[i:i + BATCH_SIZE]
                        results = await asyncio.gather(*[fetch_bn(c) for c in batch])
                        total_stored += await self._store_funding(exchange, results)
                        if i + BATCH_SIZE < len(stale):
                            await asyncio.sleep(BATCH_DELAY)
            else:
                # OKX / Bybit — use FundingRankService (no cooldown issue)
                async def fetch_other(coin: str):
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
                    batch = stale[i:i + BATCH_SIZE]
                    results = await asyncio.gather(*[fetch_other(c) for c in batch])
                    total_stored += await self._store_funding(exchange, results)
                    if i + BATCH_SIZE < len(stale):
                        await asyncio.sleep(BATCH_DELAY)

            if total_stored > 0:
                logger.info("Funding backfill [%s]: done — %d records", exchange, total_stored)

    async def _store_funding(self, exchange: str, results: list) -> int:
        """Batch store funding results to DB."""
        total = 0
        async with async_session_factory() as db:
            for r in results:
                if r is None:
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
                stmt = stmt.on_duplicate_key_update(funding_rate=stmt.inserted.funding_rate)
                await db.execute(stmt)
                total += len(values)
            await db.commit()
        return total

    async def _get_stale_funding_coins(self, exchange: str, coins: set[str]) -> list[str]:
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
        """Get Binance symbols — raw aiohttp with DB fallback."""
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(f"{BN_API}/fapi/v1/exchangeInfo") as resp:
                    if resp.status == 200:
                        info = await resp.json()
                        symbols = [
                            s["symbol"] for s in info.get("symbols", [])
                            if s.get("contractType") in ("PERPETUAL", "TRADIFI_PERPETUAL")
                            and s.get("quoteAsset") == "USDT"
                            and s.get("status") == "TRADING"
                        ]
                        if symbols:
                            return symbols
        except Exception:
            pass
        # DB fallback
        try:
            async with async_session_factory() as db:
                result = await db.execute(select(PriceKline.symbol).distinct())
                symbols = [row[0] for row in result.all()]
                if symbols:
                    return symbols
        except Exception:
            pass
        return []

    async def _refresh_bn_spot_symbols(self) -> None:
        """Refresh Binance USDT spot trading pairs. Runs at most once per day."""
        now = time.time()
        if now - self._bn_spot_last_refresh < 86400:  # 24 hours
            return

        try:
            from app.config import get_proxy
            proxy = get_proxy() or None
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Binance spot API (not futures)
                async with session.get("https://api.binance.com/api/v3/exchangeInfo",
                                       proxy=proxy) as resp:
                    if resp.status != 200:
                        return
                    info = await resp.json()

            symbols = info.get("symbols", [])
            spot_coins: list[dict[str, str]] = []
            for s in symbols:
                if (
                    s.get("quoteAsset") == "USDT"
                    and s.get("status") == "TRADING"
                    and s.get("isSpotTradingAllowed", False)
                ):
                    coin = s.get("baseAsset", "")
                    if coin:
                        spot_coins.append({"coin": coin, "symbol": s["symbol"]})

            if not spot_coins:
                return

            async with async_session_factory() as db:
                for sc in spot_coins:
                    stmt = mysql_insert(BnSpotSymbol).values(
                        coin=sc["coin"], symbol=sc["symbol"]
                    )
                    stmt = stmt.on_duplicate_key_update(
                        symbol=stmt.inserted.symbol
                    )
                    await db.execute(stmt)
                await db.commit()

            self._bn_spot_last_refresh = now
            logger.info("BN spot symbols refreshed: %d coins", len(spot_coins))
        except Exception as exc:
            logger.error("BN spot symbols refresh failed: %s", exc, exc_info=True)


# Singleton
data_backfill_scheduler = DataBackfillScheduler()
