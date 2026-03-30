from fastapi import APIRouter

from app.schedulers.funding_break_scheduler import funding_break_scheduler

router = APIRouter(prefix="/api/funding-break", tags=["funding-break"])


@router.get("")
async def get_breaking_coins():
    """Get list of coins about to break settlement cycle."""
    cached = funding_break_scheduler.get_cached_data()
    if cached:
        return {"data": cached}
    # If no cached data yet, fetch on-demand
    from app.services.funding_break import FundingBreakService
    service = FundingBreakService()
    data = await service.get_breaking_coins()
    return {"data": data}
