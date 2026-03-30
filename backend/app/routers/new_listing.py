import logging
from typing import Any

from fastapi import APIRouter

from app.schedulers.new_listing_scheduler import new_listing_scheduler
from app.schedulers.kline_scheduler import kline_scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/new-listing", tags=["new-listing"])


@router.get("")
async def get_new_listings() -> dict[str, Any]:
    """
    Get unified list of newly listed coins across all exchanges.
    Returns a flat list with exchange field on each item.
    """
    data = await new_listing_scheduler.get_cached_data_async()

    # If no cached data yet, trigger a fresh fetch
    if not any(data.values()):
        await new_listing_scheduler.refresh()
        data = await new_listing_scheduler.get_cached_data_async()

    # Merge all exchanges into a flat list
    all_items: list[dict[str, Any]] = []
    for exchange_items in data.values():
        all_items.extend(exchange_items)

    # Merge funding cumulative from cache
    funding_cum = kline_scheduler.get_funding_cumulative()
    for item in all_items:
        coin = item.get("coin_name", "")
        ex = item.get("exchange", "")
        fc = funding_cum.get(f"{coin}_{ex}")
        item["funding_1d"] = fc.get("funding_1d") if fc else None
        item["funding_3d"] = fc.get("funding_3d") if fc else None

    # Sort by listing days ascending (newest first)
    all_items.sort(key=lambda x: x.get("listing_days", 0))

    return {"data": all_items}
