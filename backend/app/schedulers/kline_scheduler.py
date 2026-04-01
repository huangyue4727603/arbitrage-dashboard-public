import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select, func
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.database import async_session_factory
from app.models.market_data import PriceKline, FundingHistory
from app.services.exchange.binance import BinanceClient

logger = logging.getLogger(__name__)

# Intervals to fetch and their data retention periods
KLINE_INTERVALS = {
    "5m": {"retention_hours": 80},
    "15m": {"retention_hours": 48},
    "1h": {"retention_hours": 168},      # 7 days
    "4h": {"retention_hours": 720},      # 30 days
    "1d": {"retention_hours": 4320},     # 180 days
}

# Minimum required history (hours) for each interval to function correctly
REQUIRED_HISTORY = {
    "5m": 26,        # 5m K线需要覆盖24h+，用于1d涨幅
    "1h": 30,        # 1h备用
    "1d": 96,        # 1d需要覆盖72h，用于3d涨幅
    "15m": 32,       # MA120 × 15min = 30h
    "4h": 504,       # MA120 × 4h = 480h
}

# How many candles to fetch when backfilling each interval
BACKFILL_LIMIT = {
    "5m": 320,       # ~26h
    "1h": 48,        # 48h
    "1d": 7,         # 7d
    "15m": 130,      # ~32h
    "4h": 130,       # ~21d
}


class KlineScheduler:
    """Scheduler that periodically fetches and stores price klines from Binance."""

    def __init__(self) -> None:
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._symbols_cache: Optional[list[str]] = None
        self._initial_fill_done: bool = True  # DB already has historical data
        self._price_changes: dict[str, dict[str, Any]] = {}  # coin -> {change_1d, change_3d}
        self._funding_cumulative: dict[str, dict[str, Any]] = {}  # "coin_exchange" -> {funding_1d, funding_3d}
        self._backfill_queue: list[tuple[str, str]] = []  # (symbol, interval) pairs to backfill
        self._backfill_checked: bool = False

    async def _get_symbols(self) -> list[str]:
        """Get all USDT perpetual symbols from Binance."""
        if self._symbols_cache:
            return self._symbols_cache
        try:
            async with BinanceClient() as client:
                info = await client.get_exchange_info()
            symbols = []
            for s in info.get("symbols", []):
                if (
                    s.get("contractType") == "PERPETUAL"
                    and s.get("quoteAsset") == "USDT"
                    and s.get("status") == "TRADING"
                ):
                    symbols.append(s["symbol"])
            self._symbols_cache = symbols
            logger.info("Kline scheduler: cached %d symbols", len(symbols))
            return symbols
        except Exception as exc:
            logger.error("Failed to get symbols for kline: %s", exc)
            return self._symbols_cache or []

    # ------------------------------------------------------------------
    # Startup data check
    # ------------------------------------------------------------------

    async def check_data_integrity(self) -> None:
        """Check DB for missing/sparse kline data, build backfill queue.

        Runs once on startup. Checks data DENSITY (not just existence)
        to detect gaps from incomplete fetches.
        """
        if self._backfill_checked:
            return

        symbols = await self._get_symbols()
        if not symbols:
            logger.warning("No symbols found, skipping data check")
            self._backfill_checked = True
            return

        logger.info("=== Checking kline data integrity (density check) ===")
        queue: list[tuple[str, str]] = []

        # Expected candle counts per interval for the required history period
        # e.g. 5m interval over 26h = 26*12 = 312 candles, require at least 70%
        expected_counts = {
            "5m": int(REQUIRED_HISTORY["5m"] * 12 * 0.7),     # ~218
            "1h": int(REQUIRED_HISTORY["1h"] * 1 * 0.7),       # ~21
            "1d": int(REQUIRED_HISTORY["1d"] / 24 * 0.7),      # ~2
            "15m": int(REQUIRED_HISTORY["15m"] * 4 * 0.7),     # ~89
            "4h": int(REQUIRED_HISTORY["4h"] / 4 * 0.7),       # ~88
        }

        for interval, required_hours in REQUIRED_HISTORY.items():
            cutoff = datetime.utcnow() - timedelta(hours=required_hours)
            min_count = expected_counts.get(interval, 1)

            try:
                async with async_session_factory() as db:
                    # Count klines per symbol within the required period
                    result = await db.execute(
                        select(PriceKline.symbol, func.count().label("cnt"))
                        .where(PriceKline.interval_type == interval)
                        .where(PriceKline.kline_time >= cutoff)
                        .group_by(PriceKline.symbol)
                    )
                    symbol_counts = {row[0]: row[1] for row in result.all()}

                # Find symbols with sparse or no data
                sparse = []
                for s in symbols:
                    cnt = symbol_counts.get(s, 0)
                    if cnt < min_count:
                        sparse.append(s)

                if sparse:
                    logger.info("[%s] Sparse/missing: %d/%d symbols (need %d+ candles in %dh, have less)",
                                interval, len(sparse), len(symbols), min_count, required_hours)
                    for s in sparse:
                        queue.append((s, interval))
                else:
                    logger.info("[%s] OK: all %d symbols have sufficient density (%d+ candles)",
                                interval, len(symbols), min_count)
            except Exception as exc:
                logger.error("Failed to check %s data: %s", interval, exc)

        self._backfill_queue = queue
        self._backfill_checked = True

        if queue:
            logger.info("=== Backfill queue: %d tasks, will process gradually (5 per 30s) ===", len(queue))
        else:
            logger.info("=== All kline data is complete ===")

    async def backfill_batch(self) -> None:
        """Process a batch from the backfill queue.

        Runs every 30 seconds, processes 20 items with concurrency 5.
        251 proxy IPs available so rate limits are not a concern.
        Pauses on 418 errors as a safety net.
        """
        if not self._backfill_queue:
            return

        batch_size = 20
        batch = self._backfill_queue[:batch_size]

        success = 0
        rate_limited = False
        semaphore = asyncio.Semaphore(5)

        async def fetch_one(client: BinanceClient, symbol: str, interval: str) -> bool:
            nonlocal rate_limited
            async with semaphore:
                if rate_limited:
                    return False
                try:
                    limit = BACKFILL_LIMIT.get(interval, 50)
                    klines = await client.get_klines(
                        symbol=symbol, interval=interval, limit=limit, timeout=20
                    )
                    if not klines:
                        return False

                    async with async_session_factory() as db:
                        for k in klines:
                            kline_time = datetime.utcfromtimestamp(int(k[0]) / 1000)
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
                    return True
                except Exception as exc:
                    err_str = str(exc)
                    if "418" in err_str or "teapot" in err_str.lower():
                        logger.warning("Backfill: Binance rate limited (418), pausing backfill")
                        rate_limited = True
                        return False
                    logger.debug("Backfill failed %s %s: %s", symbol, interval, exc)
                    return False

        async with BinanceClient() as client:
            tasks = [fetch_one(client, symbol, interval) for symbol, interval in batch]
            results = await asyncio.gather(*tasks)
            success = sum(1 for r in results if r)

        if rate_limited:
            # Don't remove items from queue, will retry later
            logger.info("Backfill paused: %d remaining (rate limited)", len(self._backfill_queue))
            return

        # Only remove successfully processed items
        self._backfill_queue = self._backfill_queue[batch_size:]
        remaining = len(self._backfill_queue)
        logger.info("Backfill: %d/%d success, %d remaining", success, len(batch), remaining)

        # When backfill completes, recompute price changes
        if remaining == 0:
            logger.info("=== Backfill complete! Recomputing price changes ===")
            await self.refresh_price_changes()

    # ------------------------------------------------------------------
    # Periodic refresh (original logic)
    # ------------------------------------------------------------------

    async def refresh_interval(self, interval: str) -> None:
        """Fetch latest klines for a single interval and save to DB."""
        symbols = await self._get_symbols()
        if not symbols:
            return

        # First run: fetch 120 candles for MA calculation; subsequent: fetch 2
        limit = 120 if not self._initial_fill_done else 2

        semaphore = asyncio.Semaphore(3)

        async def fetch_and_save(client: BinanceClient, symbol: str) -> int:
            async with semaphore:
                try:
                    klines = await client.get_klines(
                        symbol=symbol, interval=interval, limit=limit, timeout=15
                    )
                    if not klines:
                        return 0

                    count = 0
                    async with async_session_factory() as db:
                        for k in klines:
                            kline_time = datetime.utcfromtimestamp(int(k[0]) / 1000)
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
                            count += 1
                        await db.commit()
                    return count
                except Exception as exc:
                    logger.debug("Kline fetch failed %s %s: %s", symbol, interval, exc)
                    return 0

        async with BinanceClient() as client:
            tasks = [fetch_and_save(client, symbol) for symbol in symbols]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            saved = sum(r for r in results if isinstance(r, int))
            logger.info("Kline refresh [%s]: saved %d records for %d symbols (limit=%d)",
                        interval, saved, len(symbols), limit)

        if not self._initial_fill_done:
            self._initial_fill_done = True

    async def refresh(self) -> None:
        """Fetch all intervals (used for initial fill only)."""
        for interval in KLINE_INTERVALS:
            await self.refresh_interval(interval)
        await self._cleanup_old_data()

    async def _cleanup_old_data(self) -> None:
        """Delete klines older than their retention period."""
        async with async_session_factory() as db:
            try:
                for interval, config in KLINE_INTERVALS.items():
                    cutoff = datetime.utcnow() - timedelta(hours=config["retention_hours"])
                    await db.execute(
                        delete(PriceKline)
                        .where(PriceKline.interval_type == interval)
                        .where(PriceKline.kline_time < cutoff)
                    )
                await db.commit()
            except Exception as exc:
                logger.error("Failed to cleanup old klines: %s", exc)
                await db.rollback()

    async def refresh_price_changes(self) -> None:
        """Compute 1d/3d price changes.

        1d: Binance GET /fapi/v1/ticker/24hr (1 API call, all symbols).
        3d: from DB 1d klines.
        """
        try:
            changes: dict[str, dict[str, Any]] = {}

            # --- 1d: Binance 24hr ticker (single API call) ---
            try:
                async with BinanceClient() as client:
                    tickers = await client.get_24hr_ticker(timeout=20)
                if isinstance(tickers, list):
                    for t in tickers:
                        symbol = t.get("symbol", "")
                        if not symbol.endswith("USDT"):
                            continue
                        pct = t.get("priceChangePercent")
                        if pct is not None:
                            coin = symbol[:-4]
                            changes[coin] = {"change_1d": round(float(pct), 2)}
                    logger.info("1d price changes from ticker API: %d coins", len(changes))
                else:
                    logger.warning("1d ticker returned non-list: %s", type(tickers))
            except Exception as exc:
                logger.error("Failed to fetch 24hr ticker: %s", exc)

            # --- 3d: from DB 1d klines ---
            try:
                now = datetime.utcnow()
                t_3d = now - timedelta(hours=72)

                async with async_session_factory() as db:
                    # Current price: latest 1d kline close
                    latest_subq = (
                        select(PriceKline.symbol, func.max(PriceKline.kline_time).label("max_time"))
                        .where(PriceKline.interval_type == "1d")
                        .group_by(PriceKline.symbol)
                        .subquery()
                    )
                    latest_result = await db.execute(
                        select(PriceKline.symbol, PriceKline.close_price)
                        .join(latest_subq, (PriceKline.symbol == latest_subq.c.symbol) &
                              (PriceKline.kline_time == latest_subq.c.max_time))
                        .where(PriceKline.interval_type == "1d")
                    )
                    latest_prices = {row[0]: row[1] for row in latest_result.all()}

                    # 72h ago: 1d kline (±1 day window)
                    lo = t_3d - timedelta(days=1)
                    hi = t_3d + timedelta(days=1)
                    subq_3d = (
                        select(
                            PriceKline.symbol,
                            func.max(PriceKline.kline_time).label("nearest_time"),
                        )
                        .where(PriceKline.interval_type == "1d")
                        .where(PriceKline.kline_time.between(lo, hi))
                        .group_by(PriceKline.symbol)
                        .subquery()
                    )
                    result_3d = await db.execute(
                        select(PriceKline.symbol, PriceKline.close_price)
                        .where(PriceKline.interval_type == "1d")
                        .join(subq_3d, (PriceKline.symbol == subq_3d.c.symbol) &
                              (PriceKline.kline_time == subq_3d.c.nearest_time))
                    )
                    prices_3d = {row[0]: row[1] for row in result_3d.all()}

                for symbol, current in latest_prices.items():
                    coin = symbol[:-4] if symbol.endswith("USDT") else symbol
                    old_3d = prices_3d.get(symbol)
                    if old_3d and old_3d > 0:
                        change_3d = round((current - old_3d) / old_3d * 100, 2)
                        if coin in changes:
                            changes[coin]["change_3d"] = change_3d
                        else:
                            changes[coin] = {"change_3d": change_3d}
                logger.info("3d price changes from DB: %d coins", len(prices_3d))
            except Exception as exc:
                logger.error("Failed to compute 3d changes: %s", exc)

            self._price_changes = changes
            logger.info("Price changes computed: %d coins total", len(changes))
        except Exception as exc:
            logger.error("Failed to compute price changes: %s", exc)

    async def refresh_funding_cumulative(self) -> None:
        """Compute 1d/3d cumulative funding rates from DB (per coin+exchange)."""
        try:
            now = datetime.utcnow()
            t_1d = now - timedelta(hours=24)
            t_3d = now - timedelta(hours=72)

            async with async_session_factory() as db:
                # 1d cumulative: sum of funding_rate in last 24h per (coin, exchange)
                result_1d = await db.execute(
                    select(
                        FundingHistory.coin,
                        FundingHistory.exchange,
                        func.sum(FundingHistory.funding_rate).label("total"),
                    )
                    .where(FundingHistory.funding_time >= t_1d)
                    .group_by(FundingHistory.coin, FundingHistory.exchange)
                )
                cum_1d = {}
                for row in result_1d.all():
                    key = f"{row[0]}_{row[1]}"
                    cum_1d[key] = round(row[2] * 100, 3)

                # 3d cumulative
                result_3d = await db.execute(
                    select(
                        FundingHistory.coin,
                        FundingHistory.exchange,
                        func.sum(FundingHistory.funding_rate).label("total"),
                    )
                    .where(FundingHistory.funding_time >= t_3d)
                    .group_by(FundingHistory.coin, FundingHistory.exchange)
                )
                cum_3d = {}
                for row in result_3d.all():
                    key = f"{row[0]}_{row[1]}"
                    cum_3d[key] = round(row[2] * 100, 3)

            # Merge into single dict
            all_keys = set(cum_1d.keys()) | set(cum_3d.keys())
            result: dict[str, dict[str, Any]] = {}
            for key in all_keys:
                entry: dict[str, Any] = {}
                if key in cum_1d:
                    entry["funding_1d"] = cum_1d[key]
                if key in cum_3d:
                    entry["funding_3d"] = cum_3d[key]
                result[key] = entry

            self._funding_cumulative = result
            logger.info("Funding cumulative computed: %d coin-exchange pairs", len(result))
        except Exception as exc:
            logger.error("Failed to compute funding cumulative: %s", exc)

    def get_price_changes(self) -> dict[str, dict[str, Any]]:
        """Return cached price changes."""
        return self._price_changes

    def get_funding_cumulative(self) -> dict[str, dict[str, Any]]:
        """Return cached funding cumulative data."""
        return self._funding_cumulative

    def start(self) -> None:
        """Start the periodic schedulers."""
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()

        # Startup: check data integrity (DB query only, no API calls)
        self._scheduler.add_job(
            self.check_data_integrity,
            id="kline_check",
            name="Check kline data integrity",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=5),
        )

        # Backfill: 20 items every 30 seconds (251 proxy IPs, rate limits not a concern)
        self._scheduler.add_job(
            self.backfill_batch,
            trigger=IntervalTrigger(seconds=30),
            id="kline_backfill",
            name="Kline backfill",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=30),
        )

        # Kline data refresh: all intervals every 5 min, aligned to candle close + 5s
        # 251 IPs available, ~2725 req/5min = ~11 req/min/IP, well within limits
        self._scheduler.add_job(
            self.refresh,
            trigger=CronTrigger(minute="*/5", second=5),
            id="kline_refresh",
            name="Fetch kline data (all intervals)",
            replace_existing=True,
        )

        # Price changes refresh every 5 minutes (from DB, no API calls)
        self._scheduler.add_job(
            self.refresh_price_changes,
            trigger=IntervalTrigger(minutes=5),
            id="price_changes_refresh",
            name="Compute price changes",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=10),
        )

        # Funding cumulative refresh every 5 minutes (DB query)
        self._scheduler.add_job(
            self.refresh_funding_cumulative,
            trigger=IntervalTrigger(minutes=5),
            id="funding_cumulative_refresh",
            name="Compute funding cumulative",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=8),
        )

        self._scheduler.start()
        logger.info("Kline scheduler started (with startup data check + gradual backfill)")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Kline scheduler stopped")


# Module-level singleton
kline_scheduler = KlineScheduler()
