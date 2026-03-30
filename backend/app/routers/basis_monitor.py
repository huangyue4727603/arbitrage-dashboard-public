import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select

from app.database import async_session_factory
from app.models.alert_config import BasisAlertConfig
from app.services.basis_monitor import basis_monitor_service, DEFAULT_THRESHOLD, DEFAULT_MULTIPLIER
from app.utils.auth import get_optional_user_id

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/basis-monitor", tags=["basis-monitor"])


async def _get_user_config(user_id: Optional[int]) -> tuple:
    """Get user's basis config, or defaults if not logged in / not configured.
    Returns (threshold, multiplier, blocked_coins_set).
    blocked_coins = permanent_blocked + temp_blocked merged."""
    if not user_id:
        return DEFAULT_THRESHOLD, DEFAULT_MULTIPLIER, set()

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(BasisAlertConfig)
                .where(BasisAlertConfig.user_id == user_id)
            )
            config = result.scalar_one_or_none()
            if config:
                blocked = set()
                # permanent blocked (DB, survives clear)
                if config.blocked_coins:
                    blocked.update(c.strip().upper() for c in config.blocked_coins.split(",") if c.strip())
                # temp blocked (in-memory, cleared on clear)
                temp = basis_monitor_service.get_temp_blocked(user_id)
                blocked.update(temp)
                return config.basis_threshold, config.expand_multiplier, blocked
    except Exception as exc:
        logger.warning("Failed to fetch basis config for user %s: %s", user_id, exc)

    # Even without DB config, check temp blocked
    temp = basis_monitor_service.get_temp_blocked(user_id) if user_id else set()
    return DEFAULT_THRESHOLD, DEFAULT_MULTIPLIER, temp


@router.get("")
async def get_basis_data(
    user_id: Optional[int] = Depends(get_optional_user_id),
):
    """Get basis monitor data (records + timeline) from fast alert scheduler."""
    from app.schedulers.basis_alert_scheduler import basis_alert_scheduler

    threshold, multiplier, blocked = await _get_user_config(user_id)

    # Build records from alert scheduler's history
    history = basis_alert_scheduler.get_history()
    current_basis = basis_alert_scheduler.get_current_basis()
    timeline = basis_alert_scheduler.get_timeline()

    records = []
    for coin_name, abs_val in history.items():
        basis_pct = -abs_val * 100  # Convert back to negative percentage
        if basis_pct >= threshold:
            continue
        if coin_name in blocked:
            continue

        # Count alerts for this coin
        coin_alerts = [t for t in timeline if t["coin_name"] == coin_name]
        last_alert = coin_alerts[0]["time"] if coin_alerts else ""

        records.append({
            "coin_name": coin_name,
            "current_basis": current_basis.get(coin_name),
            "min_basis": round(basis_pct, 4),
            "alert_count": len(coin_alerts),
            "last_alert_at": last_alert,
        })

    records.sort(key=lambda x: x["min_basis"])

    # Filter timeline
    filtered_timeline = [
        t for t in timeline
        if t["basis"] < threshold and t["coin_name"] not in blocked
    ][:200]

    # Enrich records with 24h price changes
    from app.schedulers.kline_scheduler import kline_scheduler
    price_changes = kline_scheduler.get_price_changes()

    for record in records:
        pc = price_changes.get(record["coin_name"])
        record["change_1d"] = pc.get("change_1d") if pc else None

    return {"data": {"records": records, "timeline": filtered_timeline}}


@router.post("/refresh")
async def refresh_data(
    user_id: Optional[int] = Depends(get_optional_user_id),
):
    """Force refresh: trigger a tick on basis_alert_scheduler, then return data."""
    from app.schedulers.basis_alert_scheduler import basis_alert_scheduler
    await basis_alert_scheduler.tick()

    # Reuse the GET endpoint logic
    return await get_basis_data(user_id)


@router.post("/clear")
async def clear_records():
    """Clear all basis monitor records and timeline."""
    from app.schedulers.basis_alert_scheduler import basis_alert_scheduler
    basis_alert_scheduler.clear()
    basis_monitor_service.clear()
    return {"status": "ok"}


@router.get("/coin-alerts")
async def get_coin_alerts(coin: str = Query(...)):
    """Get all alert history for a specific coin."""
    from app.schedulers.basis_alert_scheduler import basis_alert_scheduler
    alerts = [t for t in basis_alert_scheduler.get_timeline() if t["coin_name"] == coin]
    return {"data": alerts}


@router.get("/config")
async def get_config(
    user_id: Optional[int] = Depends(get_optional_user_id),
):
    """Get user's basis monitor config."""
    perm_blocked = ""
    threshold, multiplier = DEFAULT_THRESHOLD, DEFAULT_MULTIPLIER
    if user_id:
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(BasisAlertConfig).where(BasisAlertConfig.user_id == user_id)
                )
                config = result.scalar_one_or_none()
                if config:
                    threshold = config.basis_threshold
                    multiplier = config.expand_multiplier
                    perm_blocked = config.blocked_coins or ""
        except Exception:
            pass

    temp_blocked = ",".join(sorted(basis_monitor_service.get_temp_blocked(user_id))) if user_id else ""

    return {
        "data": {
            "basis_threshold": threshold,
            "expand_multiplier": multiplier,
            "blocked_coins": perm_blocked,
            "temp_blocked_coins": temp_blocked,
        }
    }


@router.put("/config")
async def update_config(
    basis_threshold: float = Query(...),
    expand_multiplier: float = Query(...),
    blocked_coins: str = Query(""),
    temp_blocked_coins: str = Query(""),
    user_id: Optional[int] = Depends(get_optional_user_id),
):
    """Update user's basis monitor config. Requires login."""
    if not user_id:
        raise HTTPException(status_code=401, detail="需要登录才能修改配置")

    # Normalize permanent blocked (saved to DB)
    perm_normalized = ",".join(c.strip().upper() for c in blocked_coins.split(",") if c.strip()) if blocked_coins else ""

    # Normalize temp blocked (saved in memory)
    temp_set = {c.strip().upper() for c in temp_blocked_coins.split(",") if c.strip()} if temp_blocked_coins else set()
    basis_monitor_service.set_temp_blocked(user_id, temp_set)

    try:
        async with async_session_factory() as db:
            result = await db.execute(
                select(BasisAlertConfig)
                .where(BasisAlertConfig.user_id == user_id)
            )
            config = result.scalar_one_or_none()

            if config:
                config.basis_threshold = basis_threshold
                config.expand_multiplier = expand_multiplier
                config.blocked_coins = perm_normalized
            else:
                config = BasisAlertConfig(
                    user_id=user_id,
                    basis_threshold=basis_threshold,
                    expand_multiplier=expand_multiplier,
                    blocked_coins=perm_normalized,
                )
                db.add(config)

            await db.commit()

        # Invalidate scheduler cache so new threshold takes effect immediately
        from app.schedulers.basis_alert_scheduler import basis_alert_scheduler
        basis_alert_scheduler.invalidate_config()

        return {"status": "ok"}
    except Exception as exc:
        logger.error("Failed to update basis config: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
