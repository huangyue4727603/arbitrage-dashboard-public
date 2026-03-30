from fastapi import APIRouter

from app.services.unhedged import unhedged_service

router = APIRouter(prefix="/api/unhedged", tags=["unhedged"])


@router.get("")
async def get_unhedged():
    """Get current unhedged opportunity list."""
    alerts = unhedged_service.get_alerts()
    type1 = [a for a in alerts if a.get("type") == "type1"]
    type2 = [a for a in alerts if a.get("type") == "type2"]
    return {
        "type1": type1,
        "type2": type2,
    }
