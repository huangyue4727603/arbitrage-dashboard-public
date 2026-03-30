import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services.data_fetcher import data_fetcher
from app.services.basis_monitor import basis_monitor_service
from app.services.unhedged import unhedged_service
from app.services.alert_engine import alert_engine
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


class RealtimeScheduler:
    """3-second polling scheduler that shares data across modules."""

    def __init__(self) -> None:
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._running: bool = False

    async def _do_tick(self) -> None:
        """Core tick logic, called with a total timeout guard."""
        # 1. Fetch data
        data: Dict[str, Any] = await data_fetcher.fetch_all_data()
        if not data:
            return

        # 2. Update basis monitor display data (for the monitoring page)
        # Alerting is handled by the dedicated basis_alert_scheduler (3s)
        basis_monitor_service.process_data(data)

        # 3. Process unhedged opportunities
        unhedged_alerts = await unhedged_service.process_data(data)

        # 4. Push via WebSocket
        await manager.broadcast("basisMonitor", {"updated": True})
        if unhedged_alerts:
            all_unhedged = unhedged_service.get_alerts()
            type1 = [a for a in all_unhedged if a.get("type") == "type1"]
            type2 = [a for a in all_unhedged if a.get("type") == "type2"]
            await manager.broadcast("unhedged", {"type1": type1, "type2": type2})

        # 5. Alert engine
        if unhedged_alerts:
            try:
                await alert_engine.process_unhedged_alert({"alerts": unhedged_alerts})
            except Exception as exc:
                logger.error("Alert engine unhedged processing failed: %s", exc)

        # 6. Process post-investment monitors
        try:
            await alert_engine.process_post_investment(data)
        except Exception as exc:
            logger.error("Alert engine post-investment processing failed: %s", exc)

    async def tick(self) -> None:
        """Called every 3 seconds. Wraps _do_tick with timeout and guard."""
        if self._running:
            return
        self._running = True
        try:
            await asyncio.wait_for(self._do_tick(), timeout=210)
        except asyncio.TimeoutError:
            logger.warning("Realtime tick timed out (210s)")
        except Exception as exc:
            logger.error("Realtime scheduler tick failed: %s", exc)
        finally:
            self._running = False

    def start(self) -> None:
        """Start the periodic scheduler."""
        if self._scheduler is not None:
            return

        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.tick,
            trigger=IntervalTrigger(seconds=3),
            id="realtime_tick",
            name="Realtime data polling (3s)",
            replace_existing=True,
            next_run_time=datetime.now(),
        )
        self._scheduler.start()
        logger.info("Realtime scheduler started (interval=3s)")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Realtime scheduler stopped")


# Module-level singleton
realtime_scheduler = RealtimeScheduler()
