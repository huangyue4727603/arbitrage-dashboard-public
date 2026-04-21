"""Open Interest & Long/Short Ratio scheduler.

Fetches OI and LSR for all Binance USDT perpetual symbols every 5 minutes.
Uses raw aiohttp to bypass BinanceClient cooldown.

Binance APIs:
  - OI: GET /fapi/v1/openInterest?symbol=X  (returns qty in base asset)
  - LSR: GET /futures/data/globalLongShortAccountRatio?symbol=X&period=5m&limit=1
  - Prices: GET /fapi/v2/ticker/price  (bulk, all symbols in 1 call)
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select, delete
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.database import async_session_factory
from app.models.market_data import OiSnapshot5m, LsrSnapshot5m, PriceKline

logger = logging.getLogger(__name__)

BN_API = "https://fapi.binance.com"
BN_DATA_API = "https://fapi.binance.com"
RETENTION_HOURS = 168  # 7 days
BATCH_SIZE = 20
TIMEOUT = aiohttp.ClientTimeout(total=15)


class OiLsrScheduler:
    """Fetches and stores OI + LSR every 5 minutes."""

    def __init__(self) -> None:
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._symbols_cache: Optional[list[str]] = None
        # Latest data in memory for fast API access
        self._latest_oi: dict[str, float] = {}     # symbol -> oi_usdt
        self._latest_lsr: dict[str, float] = {}    # symbol -> long_short_ratio

    def get_latest_oi(self) -> dict[str, float]:
        return self._latest_oi

    def get_latest_lsr(self) -> dict[str, float]:
        return self._latest_lsr

    async def _get_symbols(self) -> list[str]:
        """Get symbols from cache or DB."""
        if self._symbols_cache:
            return self._symbols_cache
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
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
                            self._symbols_cache = symbols
                            return symbols
        except Exception:
            pass
        # DB fallback
        try:
            async with async_session_factory() as db:
                result = await db.execute(select(PriceKline.symbol).distinct())
                symbols = [row[0] for row in result.all()]
                if symbols:
                    self._symbols_cache = symbols
                return symbols
        except Exception:
            return []

    async def refresh(self) -> None:
        """Fetch OI + LSR for all symbols and store."""
        symbols = await self._get_symbols()
        if not symbols:
            logger.warning("OI/LSR: no symbols")
            return

        now = datetime.now().replace(second=0, microsecond=0)
        sem = asyncio.Semaphore(10)

        # Step 1: Extract OI from data_fetcher cache (no extra API calls)
        oi_data: dict[str, float] = {}
        try:
            from app.services.data_fetcher import data_fetcher
            cached = data_fetcher.get_cached_data()
            for pair_key, pair_data in cached.items():
                if not pair_data or not isinstance(pair_data, dict):
                    continue
                items = pair_data.get("data", pair_data)
                if isinstance(items, dict):
                    items = items.get("data", [])
                if not isinstance(items, list):
                    continue
                for item in items:
                    coin = item.get("coinName", "")
                    if not coin:
                        continue
                    symbol = coin + "USDT" if not coin.endswith("USDT") else coin
                    # Extract OI — longOpenInterest is in USDT already
                    long_ex = item.get("longExchange", "")
                    short_ex = item.get("shortExchange", "")
                    oi_val = float(item.get("longOpenInterest", 0) or 0)
                    if oi_val > 0:
                        # Use BN OI when BN is the long exchange
                        if long_ex == "BINANCE" and symbol not in oi_data:
                            oi_data[symbol] = oi_val
                        # For any exchange pair, store if we don't have it yet
                        elif symbol not in oi_data:
                            oi_data[symbol] = oi_val
        except Exception as exc:
            logger.error("OI extraction from cache failed: %s", exc)

        # Step 2: Fetch LSR per symbol (Binance REST, different endpoint not affected by 418)
        lsr_data: dict[str, float] = {}

        async def fetch_lsr(session: aiohttp.ClientSession, symbol: str):
            async with sem:
                try:
                    async with session.get(
                        f"{BN_DATA_API}/futures/data/globalLongShortAccountRatio",
                        params={"symbol": symbol, "period": "5m", "limit": 1}
                    ) as resp:
                        if resp.status != 200:
                            return
                        data = await resp.json()
                        if data and isinstance(data, list) and len(data) > 0:
                            ratio = float(data[0].get("longShortRatio", 0))
                            if ratio > 0:
                                lsr_data[symbol] = ratio
                except Exception:
                    pass

        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            for i in range(0, len(symbols), BATCH_SIZE):
                batch = symbols[i:i + BATCH_SIZE]
                await asyncio.gather(*[fetch_lsr(session, s) for s in batch])
                if i + BATCH_SIZE < len(symbols):
                    await asyncio.sleep(0.2)

        # Step 4: Store to DB
        if oi_data:
            try:
                async with async_session_factory() as db:
                    values = [
                        {"symbol": sym, "oi_usdt": val, "snapshot_time": now}
                        for sym, val in oi_data.items()
                    ]
                    stmt = mysql_insert(OiSnapshot5m).values(values)
                    stmt = stmt.on_duplicate_key_update(oi_usdt=stmt.inserted.oi_usdt)
                    await db.execute(stmt)
                    await db.commit()
            except Exception as exc:
                logger.error("OI store failed: %s", exc)

        if lsr_data:
            try:
                async with async_session_factory() as db:
                    values = [
                        {"symbol": sym, "long_short_ratio": val, "snapshot_time": now}
                        for sym, val in lsr_data.items()
                    ]
                    stmt = mysql_insert(LsrSnapshot5m).values(values)
                    stmt = stmt.on_duplicate_key_update(long_short_ratio=stmt.inserted.long_short_ratio)
                    await db.execute(stmt)
                    await db.commit()
            except Exception as exc:
                logger.error("LSR store failed: %s", exc)

        # Update in-memory cache
        self._latest_oi = oi_data
        self._latest_lsr = lsr_data

        logger.info("OI/LSR refresh: OI=%d, LSR=%d symbols", len(oi_data), len(lsr_data))

    async def _cleanup(self) -> None:
        """Remove data older than retention period."""
        cutoff = datetime.now() - timedelta(hours=RETENTION_HOURS)
        try:
            async with async_session_factory() as db:
                await db.execute(delete(OiSnapshot5m).where(OiSnapshot5m.snapshot_time < cutoff))
                await db.execute(delete(LsrSnapshot5m).where(LsrSnapshot5m.snapshot_time < cutoff))
                await db.commit()
        except Exception as exc:
            logger.error("OI/LSR cleanup failed: %s", exc)

    def start(self) -> None:
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()

        # Run every 5 minutes aligned to :00, :05, :10, ...
        self._scheduler.add_job(
            self.refresh,
            trigger=CronTrigger(minute="*/5", second=10),
            id="oi_lsr_refresh",
            name="Fetch OI & LSR data",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=10),
        )

        # Cleanup every hour
        self._scheduler.add_job(
            self._cleanup,
            trigger=CronTrigger(minute=30),
            id="oi_lsr_cleanup",
            name="Cleanup old OI/LSR data",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info("OI/LSR scheduler started (5min interval)")

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("OI/LSR scheduler stopped")


# Singleton
oi_lsr_scheduler = OiLsrScheduler()
