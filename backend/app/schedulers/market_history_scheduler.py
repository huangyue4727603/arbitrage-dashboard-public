"""Scheduler: every 5 min fetch /chance/histories starting from MAX(created_at)-30s
overlap, dedup via seq_id unique. Hourly cleanup of >3 day rows.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services.market_history import (
    fetch_histories,
    get_max_created_at_ms,
    insert_rows,
    cleanup_old,
)

logger = logging.getLogger(__name__)

# 30s overlap window — relies on seq_id UNIQUE to dedup
OVERLAP_MS = 30_000


class MarketHistoryScheduler:
    def __init__(self) -> None:
        self._scheduler: AsyncIOScheduler | None = None

    async def fetch_and_store(self) -> None:
        try:
            last_ms = await get_max_created_at_ms()
            now_ms = int(datetime.now().timestamp() * 1000)
            if last_ms is None:
                # First run: pull last 5 min
                ts = now_ms - 5 * 60 * 1000
            else:
                ts = last_ms - OVERLAP_MS
            rows = await fetch_histories(ts)
            inserted = await insert_rows(rows)
            logger.info(
                "market_history: fetched %d rows from ts=%d, inserted %d",
                len(rows), ts, inserted,
            )
        except Exception as exc:
            logger.error("market_history fetch failed: %r", exc)

    async def cleanup(self) -> None:
        try:
            n = await cleanup_old(days=3)
            if n:
                logger.info("market_history: cleanup deleted %d old rows", n)
        except Exception as exc:
            logger.error("market_history cleanup failed: %s", exc)

    def start(self) -> None:
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.fetch_and_store,
            trigger=IntervalTrigger(minutes=5),
            id="market_history_fetch",
            name="Fetch market history (5min)",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=5),
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.add_job(
            self.cleanup,
            trigger=IntervalTrigger(hours=1),
            id="market_history_cleanup",
            name="Cleanup market history >3d",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(minutes=2),
            max_instances=1,
        )
        self._scheduler.start()
        logger.info("market_history_scheduler started (5min fetch + 1h cleanup)")

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("market_history_scheduler stopped")


market_history_scheduler = MarketHistoryScheduler()
