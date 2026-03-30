from fastapi import APIRouter

from app.schedulers.price_trend_scheduler import price_trend_scheduler

router = APIRouter(prefix="/api/price-trend", tags=["price-trend"])


@router.get("")
async def get_price_trend():
    """Get price trend (bullish alignment) data."""
    data = await price_trend_scheduler.get_cached_data_async()
    return {"data": data}


@router.post("/refresh")
async def refresh_price_trend():
    """Manually trigger a price trend refresh."""
    await price_trend_scheduler.refresh()
    data = price_trend_scheduler.get_cached_data()
    return {"data": data}
