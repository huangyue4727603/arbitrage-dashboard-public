import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services.new_listing import new_listing_service

logger = logging.getLogger(__name__)


class NewListingScheduler:
    """Scheduler that periodically refreshes new listing data for all exchanges."""

    def __init__(self) -> None:
        self._cached_data: dict[str, list[dict[str, Any]]] = {
            "okx": [],
            "binance": [],
            "bybit": [],
        }
        self._scheduler: Optional[AsyncIOScheduler] = None
        # Track known coins per exchange to detect new ones
        self._known_coins: dict[str, set[str]] = {
            "okx": set(),
            "binance": set(),
            "bybit": set(),
        }
        # Alert history (in-memory, newest first)
        self._alerts: list[dict[str, Any]] = []

    def get_cached_data(self) -> dict[str, list[dict[str, Any]]]:
        """Return the latest cached new listing data. Falls back to DB if empty."""
        return self._cached_data.copy()

    def get_alerts(self) -> list[dict[str, Any]]:
        """Return new listing alert history."""
        return self._alerts

    def clear_alerts(self) -> None:
        """Clear alert history."""
        self._alerts = []

    async def get_cached_data_async(self) -> dict[str, list[dict[str, Any]]]:
        """Return cached data, falling back to DB if memory is empty."""
        has_data = any(len(v) > 0 for v in self._cached_data.values())
        if not has_data:
            # Load from DB
            for exchange in ["okx", "binance", "bybit"]:
                try:
                    db_data = await new_listing_service.get_from_db(exchange)
                    if db_data:
                        self._cached_data[exchange] = db_data
                except Exception as exc:
                    logger.error("Failed to load %s listings from DB: %s", exchange, exc)
        return self._cached_data.copy()

    async def refresh(self) -> None:
        """Fetch new listing data from all exchanges concurrently."""
        logger.info("Refreshing new listing data for all exchanges...")
        try:
            okx_task = new_listing_service.get_new_listings("OKX")
            binance_task = new_listing_service.get_new_listings("BINANCE")
            bybit_task = new_listing_service.get_new_listings("BYBIT")

            okx_data, binance_data, bybit_data = await asyncio.gather(
                okx_task, binance_task, bybit_task, return_exceptions=True
            )

            exchange_map = {
                "okx": okx_data,
                "binance": binance_data,
                "bybit": bybit_data,
            }
            exchange_label = {"okx": "OKX", "binance": "BINANCE", "bybit": "BYBIT"}
            now = datetime.now()

            for ex_key, data in exchange_map.items():
                if isinstance(data, list):
                    self._cached_data[ex_key] = data
                    await new_listing_service.save_to_db(exchange_label[ex_key], data)

                    # Detect new coins
                    current_coins = {item.get("coin_name", "") for item in data if item.get("coin_name")}
                    if self._known_coins[ex_key]:
                        new_coins = current_coins - self._known_coins[ex_key]
                        for coin in new_coins:
                            alert = {
                                "coin_name": coin,
                                "exchange": exchange_label[ex_key],
                                "alert_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                                "timestamp": now.timestamp(),
                            }
                            self._alerts.insert(0, alert)
                            logger.info("New listing alert: %s on %s", coin, exchange_label[ex_key])
                    self._known_coins[ex_key] = current_coins
                else:
                    logger.error("%s new listing refresh failed: %s", exchange_label[ex_key], data)

            # Keep alerts under 200
            if len(self._alerts) > 200:
                self._alerts = self._alerts[:200]

            logger.info(
                "New listing refresh complete: OKX=%d, Binance=%d, Bybit=%d",
                len(self._cached_data["okx"]),
                len(self._cached_data["binance"]),
                len(self._cached_data["bybit"]),
            )
        except Exception as exc:
            logger.error("New listing refresh failed: %s", exc)

    def start(self) -> None:
        """Start the periodic scheduler (every 5 minutes)."""
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        from datetime import timedelta
        self._scheduler.add_job(
            self.refresh,
            trigger=IntervalTrigger(minutes=30),
            id="new_listing_refresh",
            name="Refresh new listing data",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=25),
        )
        self._scheduler.start()
        logger.info("New listing scheduler started (interval=30min)")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("New listing scheduler stopped")


# Module-level singleton
new_listing_scheduler = NewListingScheduler()
