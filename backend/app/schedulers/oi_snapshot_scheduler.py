import logging
from datetime import datetime, timedelta
from typing import Optional

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import get_proxy
from app.database import async_session_factory
from app.models.alert_config import PostInvestmentMonitor
from app.models.market_data import OISnapshot

logger = logging.getLogger(__name__)


class OISnapshotScheduler:
    """Scheduler that tracks open interest per user per symbol.

    Each user's monitor has independent max_oi_1h/max_oi_4h tracking.
    """

    def __init__(self) -> None:
        self._scheduler: Optional[AsyncIOScheduler] = None

    async def _get_active_monitors(self) -> list[dict]:
        """Get all active monitors with user_id and coin_name."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(
                    PostInvestmentMonitor.user_id,
                    PostInvestmentMonitor.coin_name,
                )
                .where(PostInvestmentMonitor.is_active == True)  # noqa: E712
            )
            return [
                {"user_id": row[0], "symbol": f"{row[1].upper()}USDT"}
                for row in result.all()
            ]

    async def _fetch_oi(self, session: aiohttp.ClientSession, symbol: str) -> Optional[float]:
        """Fetch current open interest from Binance."""
        from app.services.exchange.binance import _cooldown_map
        import time as _time
        if _time.time() < _cooldown_map.get("oi", 0.0):
            return None
        url = "https://fapi.binance.com/fapi/v1/openInterest"
        params = {"symbol": symbol}
        try:
            proxy = get_proxy() or None
            async with session.get(url, params=params, proxy=proxy) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return float(data.get("openInterest", 0))
        except Exception as exc:
            logger.debug("Failed to fetch OI for %s: %s", symbol, exc)
            return None

    async def refresh(self) -> None:
        """Snapshot OI for all monitored symbols, per user."""
        monitors = await self._get_active_monitors()
        if not monitors:
            return

        now = datetime.now()
        timeout = aiohttp.ClientTimeout(total=15)

        # Fetch OI once per unique symbol
        unique_symbols = list({m["symbol"] for m in monitors})
        oi_values: dict[str, float] = {}

        async with aiohttp.ClientSession(timeout=timeout) as session:
            for symbol in unique_symbols:
                oi = await self._fetch_oi(session, symbol)
                if oi is not None and oi > 0:
                    oi_values[symbol] = oi

        # Update per user+symbol
        async with async_session_factory() as db:
            try:
                for monitor in monitors:
                    symbol = monitor["symbol"]
                    user_id = monitor["user_id"]
                    oi = oi_values.get(symbol)
                    if oi is None:
                        continue

                    result = await db.execute(
                        select(OISnapshot)
                        .where(OISnapshot.user_id == user_id)
                        .where(OISnapshot.symbol == symbol)
                    )
                    existing = result.scalar_one_or_none()

                    if existing is None:
                        db.add(OISnapshot(
                            user_id=user_id,
                            symbol=symbol,
                            current_oi=oi,
                            max_oi_1h=oi,
                            max_oi_4h=oi,
                            max_oi_1h_reset_at=now,
                            max_oi_4h_reset_at=now,
                        ))
                    else:
                        existing.current_oi = oi

                        # 1h max: reset if >1h since last reset
                        if (now - existing.max_oi_1h_reset_at).total_seconds() >= 3600:
                            existing.max_oi_1h = oi
                            existing.max_oi_1h_reset_at = now
                        elif oi > existing.max_oi_1h:
                            existing.max_oi_1h = oi

                        # 4h max: reset if >4h since last reset
                        if (now - existing.max_oi_4h_reset_at).total_seconds() >= 14400:
                            existing.max_oi_4h = oi
                            existing.max_oi_4h_reset_at = now
                        elif oi > existing.max_oi_4h:
                            existing.max_oi_4h = oi

                await db.commit()
                logger.info("OI snapshot: updated %d monitors", len(monitors))
            except Exception as exc:
                logger.error("Failed to update OI snapshots: %s", exc)
                await db.rollback()

    def start(self) -> None:
        """Start the periodic scheduler (every 5 minutes)."""
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.refresh,
            trigger=IntervalTrigger(minutes=5),
            id="oi_snapshot_refresh",
            name="Snapshot OI data",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=10),
        )
        self._scheduler.start()
        logger.info("OI snapshot scheduler started (interval=5min)")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("OI snapshot scheduler stopped")


# Module-level singleton
oi_snapshot_scheduler = OISnapshotScheduler()
