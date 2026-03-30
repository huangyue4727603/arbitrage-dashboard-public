import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services.funding_break import funding_break_service
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


class FundingBreakScheduler:
    """Scheduler that periodically checks for funding rate cap breakthroughs.

    - Real-time data (funding rates + basis) refreshed every 5 seconds
    - Funding caps refreshed every hour (via service internal TTL)
    """

    def __init__(self) -> None:
        self._cached_data: List[Dict[str, Any]] = []
        self._service = funding_break_service
        self._scheduler: Optional[AsyncIOScheduler] = None

    def get_cached_data(self) -> List[Dict[str, Any]]:
        """Return the latest cached breaking coins data."""
        return self._cached_data

    async def refresh_data(self) -> None:
        """Refresh breaking coins data and broadcast via WebSocket."""
        try:
            data = await self._service.get_breaking_coins()
            self._cached_data = data
            # Broadcast to all connected clients
            await manager.broadcast("fundingBreak", data)
            logger.debug(
                "Funding break refresh complete: %d breaking coins", len(data)
            )
        except Exception as exc:
            logger.error("Funding break refresh failed: %s", exc)

    async def refresh_caps(self) -> None:
        """Force refresh funding caps from exchanges."""
        try:
            await self._service.force_refresh_caps()
            logger.info("Funding break caps force-refreshed")
        except Exception as exc:
            logger.error("Funding break caps refresh failed: %s", exc)

    def start(self) -> None:
        """Start the periodic scheduler."""
        if self._scheduler is not None:
            return
        from datetime import timedelta
        self._scheduler = AsyncIOScheduler()
        # Refresh real-time data every 5 seconds (delay 10s to let realtime scheduler start first)
        self._scheduler.add_job(
            self.refresh_data,
            trigger=IntervalTrigger(seconds=5),
            id="funding_break_refresh",
            name="Refresh funding break data",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=10),
        )
        # Force refresh caps every hour
        self._scheduler.add_job(
            self.refresh_caps,
            trigger=IntervalTrigger(hours=1),
            id="funding_break_caps_refresh",
            name="Refresh funding break caps",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=15),
        )
        self._scheduler.start()
        logger.info(
            "Funding break scheduler started (data=5s, caps=1h)"
        )

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Funding break scheduler stopped")


# Module-level singleton
funding_break_scheduler = FundingBreakScheduler()
