import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

_UTC8 = timezone(timedelta(hours=8))

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, func
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.database import async_session_factory
from app.models.market_data import FundingHistory
from app.services.funding_rank import FundingRankService, BINANCE, OKX, BYBIT

logger = logging.getLogger(__name__)


class FundingRankScheduler:
    """Scheduler that periodically fetches funding history and caches rankings.

    - Funding history fetched and stored in DB every 1 hour
    - Rankings computed from DB and cached in memory
    - Spread data refreshed every 1 minute
    """

    def __init__(self) -> None:
        self._cached_rankings: list[dict[str, Any]] | None = None
        self._cached_start: int = 0
        self._cached_end: int = 0
        self._service = FundingRankService()
        self._scheduler: Optional[AsyncIOScheduler] = None

    def get_cached_rankings(self) -> dict[str, Any]:
        return {
            "data": self._cached_rankings,
            "start": self._cached_start,
            "end": self._cached_end,
        }

    async def _fetch_and_store_history(self) -> None:
        """Fetch funding history from all exchanges and store in DB."""
        # Get coins per exchange
        bn_coins, okx_coins, bybit_coins = await asyncio.gather(
            self._service._get_exchange_coins(BINANCE),
            self._service._get_exchange_coins(OKX),
            self._service._get_exchange_coins(BYBIT),
        )

        exchange_coins_map = {BINANCE: bn_coins, OKX: okx_coins, BYBIT: bybit_coins}

        # Fetch all coins (union of all exchanges)
        relevant = bn_coins | okx_coins | bybit_coins

        now_ms = int(time.time() * 1000)

        # Check latest data in DB to determine how far back to fetch
        async with async_session_factory() as db:
            result = await db.execute(
                select(func.max(FundingHistory.funding_time))
            )
            latest_time = result.scalar()

        if latest_time is None:
            start_ms = now_ms - 7 * 24 * 3600 * 1000  # 7 days
            logger.info("First funding history fetch: 7 days, %d coins", len(relevant))
        else:
            # Fetch from 1 hour before latest record to cover any gaps
            from datetime import timezone as tz
            latest_ts = int(latest_time.replace(tzinfo=_UTC8).timestamp() * 1000)
            gap_ms = now_ms - latest_ts
            gap_hours = gap_ms / 3600000
            # At least 2 hours overlap, at most 7 days
            fetch_ms = min(max(gap_ms + 3600 * 1000, 2 * 3600 * 1000), 7 * 24 * 3600 * 1000)
            start_ms = now_ms - int(fetch_ms)
            if gap_hours > 2:
                logger.info("Funding data gap detected: %.1f hours, fetching from %d hours ago",
                            gap_hours, fetch_ms / 3600000)

        sem = asyncio.Semaphore(2)

        async def fetch_one(exchange: str, coin: str):
            async with sem:
                try:
                    records = await self._service._fetch_funding_for_exchange(
                        exchange, coin, start_ms, now_ms
                    )
                    await asyncio.sleep(0.3)  # Rate limit: 300ms between requests
                    return (exchange, coin, records) if records else None
                except Exception:
                    return None

        # Fetch per exchange sequentially to avoid overwhelming any single API
        fetch_results = []
        for ex, coins_set in exchange_coins_map.items():
            coins_list = list(relevant & coins_set)
            # Process in small batches with pauses
            batch_size = 10
            for i in range(0, len(coins_list), batch_size):
                batch = coins_list[i:i + batch_size]
                tasks = [fetch_one(ex, coin) for coin in batch]
                results = await asyncio.gather(*tasks)
                fetch_results.extend(results)
                if i + batch_size < len(coins_list):
                    await asyncio.sleep(1)  # 1s pause between batches

        # Batch upsert to DB
        async with async_session_factory() as db:
            try:
                total = 0
                for r in fetch_results:
                    if r is None:
                        continue
                    exchange, coin, records = r
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
                    total += len(values)
                await db.commit()
                logger.info("Stored %d funding history records for %d coins", total, len(relevant))
            except Exception as exc:
                logger.error("Failed to store funding history: %s", exc)
                await db.rollback()

    async def check_and_backfill(self) -> None:
        """Check for missing funding data and backfill.

        Compares each coin's latest record time against its settlement period.
        If stale (latest_record + period + 5min < now), fetches last 48h.
        Runs every 10 minutes as independent scheduled job.
        """
        try:
            from app.models.market_data import FundingCap

            now = datetime.now(_UTC8).replace(tzinfo=None)
            now_ms = int(time.time() * 1000)

            # Load settlement periods from FundingCap table
            # FundingCap.exchange uses display names: "Binance", "OKX", "Bybit"
            exchange_map = {"Binance": "BN", "OKX": "OKX", "Bybit": "BY"}
            coin_periods: dict[str, dict[str, int]] = {}  # {"BN": {"PIPPIN": 1, ...}}

            async with async_session_factory() as db:
                result = await db.execute(
                    select(FundingCap.exchange, FundingCap.symbol, FundingCap.interval_hours)
                )
                for row in result.all():
                    ex_key = exchange_map.get(row[0], row[0])
                    if ex_key not in coin_periods:
                        coin_periods[ex_key] = {}
                    # symbol is like "PIPPINUSDT" -> extract coin name
                    sym = row[1]
                    if sym.endswith("USDT"):
                        coin = sym[:-4]
                    elif "-" in sym:
                        coin = sym.split("-")[0]
                    else:
                        coin = sym
                    coin_periods[ex_key][coin] = row[2] or 8

            stale_coins: list[tuple[str, str]] = []

            for exchange, periods in coin_periods.items():
                # Get latest record time per coin
                async with async_session_factory() as db:
                    result = await db.execute(
                        select(FundingHistory.coin, func.max(FundingHistory.funding_time))
                        .where(FundingHistory.exchange == exchange)
                        .group_by(FundingHistory.coin)
                    )
                    latest_times = {row[0]: row[1] for row in result.all()}

                for coin, period_hours in periods.items():
                    stale_threshold = timedelta(hours=period_hours, minutes=5)
                    latest = latest_times.get(coin)

                    if latest is None:
                        stale_coins.append((exchange, coin))
                    elif (now - latest) > stale_threshold:
                        stale_coins.append((exchange, coin))

            if not stale_coins:
                return

            logger.info("Funding backfill: %d stale coins found", len(stale_coins))

            start_ms = now_ms - 48 * 3600 * 1000
            sem = asyncio.Semaphore(2)
            total_stored = 0

            async def fetch_one(exchange: str, coin: str):
                async with sem:
                    try:
                        records = await self._service._fetch_funding_for_exchange(
                            exchange, coin, start_ms, now_ms
                        )
                        await asyncio.sleep(0.5)
                        return (exchange, coin, records) if records else None
                    except Exception:
                        return None

            for i in range(0, len(stale_coins), 5):
                batch = stale_coins[i:i + 5]
                tasks = [fetch_one(ex, coin) for ex, coin in batch]
                results = await asyncio.gather(*tasks)

                async with async_session_factory() as db:
                    for r in results:
                        if r is None:
                            continue
                        exchange, coin, records = r
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

                if i + 5 < len(stale_coins):
                    await asyncio.sleep(2)

            if total_stored > 0:
                logger.info("Funding backfill done: %d records for %d coins",
                            total_stored, len(stale_coins))
        except Exception as exc:
            logger.error("Funding backfill failed: %s", exc)

    async def refresh_funding(self) -> None:
        """Fetch funding history, store in DB, then compute rankings."""
        logger.info("Refreshing funding data...")
        try:
            await self._fetch_and_store_history()

            # Compute default 24h rankings from DB
            now_ms = int(time.time() * 1000)
            start = now_ms - 24 * 60 * 60 * 1000
            rankings = await self._service.get_rankings(start, now_ms)
            self._cached_rankings = rankings
            self._cached_start = start
            self._cached_end = now_ms
            logger.info(
                "Funding rank refresh complete: %d items",
                len(rankings),
            )
        except Exception as exc:
            logger.error("Funding rank refresh failed: %s", exc)

    async def refresh_spreads(self) -> None:
        """No longer needed - spread/basis come from realtime API endpoint."""
        pass

    def start(self) -> None:
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.refresh_funding,
            trigger=IntervalTrigger(hours=1),
            id="funding_rank_refresh",
            name="Refresh funding rank data",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=20),
        )
        self._scheduler.add_job(
            self.refresh_spreads,
            trigger=IntervalTrigger(minutes=1),
            id="funding_spread_refresh",
            name="Refresh funding spread data",
            replace_existing=True,
        )
        # Check and backfill missing funding data every 10 minutes
        self._scheduler.add_job(
            self.check_and_backfill,
            trigger=IntervalTrigger(minutes=10),
            id="funding_backfill",
            name="Check and backfill funding data",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(minutes=2),
        )
        self._scheduler.start()
        logger.info("Funding rank scheduler started (funding=1h, backfill=10min)")

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Funding rank scheduler stopped")


# Module-level singleton
funding_rank_scheduler = FundingRankScheduler()
