import logging
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, text

from app.database import async_session_factory
from app.models.alert_history import BasisAlertHistory, BasisAlertRecord
from app.models.market_data import NewListing, PriceTrend, FundingHistory

logger = logging.getLogger(__name__)


class CleanupScheduler:
    """Scheduler that periodically cleans up old data from various tables."""

    def __init__(self) -> None:
        self._scheduler: Optional[AsyncIOScheduler] = None

    async def cleanup(self) -> None:
        """Run all cleanup tasks."""
        async with async_session_factory() as db:
            try:
                now = datetime.now()

                # 1. basis_alert_history: keep 30 days
                cutoff_30d = now - timedelta(days=30)
                r1 = await db.execute(
                    delete(BasisAlertHistory).where(BasisAlertHistory.alert_at < cutoff_30d)
                )

                # 2. basis_alert_records: keep 7 days
                cutoff_7d = now - timedelta(days=7)
                r2 = await db.execute(
                    delete(BasisAlertRecord).where(BasisAlertRecord.first_alert_at < cutoff_7d)
                )

                # 3. new_listings: remove listing_days > 90
                r3 = await db.execute(
                    delete(NewListing).where(NewListing.listing_days > 90)
                )

                # 4. price_trends: remove stale (not updated in 24h)
                cutoff_24h = now - timedelta(hours=24)
                r4 = await db.execute(
                    delete(PriceTrend).where(PriceTrend.updated_at < cutoff_24h)
                )

                # 5. funding_history: keep 30 days
                r5 = await db.execute(
                    delete(FundingHistory).where(FundingHistory.funding_time < cutoff_30d)
                )

                await db.commit()
                logger.info(
                    "Cleanup done: alert_history=%d, alert_records=%d, new_listings=%d, price_trends=%d, funding_history=%d",
                    r1.rowcount, r2.rowcount, r3.rowcount, r4.rowcount, r5.rowcount,
                )
            except Exception as exc:
                logger.error("Cleanup failed: %s", exc)
                await db.rollback()

    def start(self) -> None:
        """Start the periodic scheduler (every 24 hours)."""
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.cleanup,
            trigger=IntervalTrigger(hours=24),
            id="cleanup",
            name="Cleanup old data",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(minutes=5),
        )
        self._scheduler.start()
        logger.info("Cleanup scheduler started (interval=24h)")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Cleanup scheduler stopped")


# Module-level singleton
cleanup_scheduler = CleanupScheduler()
