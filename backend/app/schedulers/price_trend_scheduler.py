import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.database import async_session_factory
from app.models.market_data import PriceTrend
from app.services.price_trend import PriceTrendService
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


class PriceTrendScheduler:
    """Scheduler that periodically refreshes price trend (bullish alignment) data."""

    def __init__(self) -> None:
        self._cached_data: List[Dict[str, Any]] = []
        self._service = PriceTrendService()
        self._scheduler: Optional[AsyncIOScheduler] = None

    def get_cached_data(self) -> List[Dict[str, Any]]:
        """Return the latest cached price trend data."""
        return self._cached_data

    async def get_cached_data_async(self) -> List[Dict[str, Any]]:
        """Return cached data, falling back to DB if memory is empty."""
        if not self._cached_data:
            try:
                async with async_session_factory() as db:
                    result = await db.execute(
                        select(PriceTrend).order_by(PriceTrend.sort_score.desc())
                    )
                    rows = result.scalars().all()
                    self._cached_data = [
                        {
                            "coin_name": r.coin_name,
                            "daily": r.daily,
                            "h4": r.h4,
                            "h1": r.h1,
                            "m15": r.m15,
                            "sort_score": r.sort_score,
                        }
                        for r in rows
                    ]
                    if self._cached_data:
                        logger.info("Loaded %d price trends from DB", len(self._cached_data))
            except Exception as exc:
                logger.error("Failed to load price trends from DB: %s", exc)
        return self._cached_data

    async def refresh(self) -> None:
        """Refresh price trend data for all Binance USDT perp symbols."""
        logger.info("Refreshing price trend data...")
        try:
            results = await self._service.calculate_all()
            self._cached_data = results
            logger.info("Price trend refresh complete: %d coins", len(results))

            # Push via WebSocket
            await manager.broadcast("priceTrend", results)
        except Exception as exc:
            logger.error("Price trend refresh failed: %s", exc)

    def start(self) -> None:
        """Start the periodic scheduler (every 10 minutes)."""
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        from datetime import timedelta
        self._scheduler.add_job(
            self.refresh,
            trigger=IntervalTrigger(minutes=10),
            id="price_trend_refresh",
            name="Refresh price trend data",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=30),
        )
        self._scheduler.start()
        logger.info("Price trend scheduler started (interval=10min)")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Price trend scheduler stopped")


# Module-level singleton
price_trend_scheduler = PriceTrendScheduler()
