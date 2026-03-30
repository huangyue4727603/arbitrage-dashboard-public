import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select, delete, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.user import User
from app.models.lark_bot import LarkBot
from app.models.alert_config import (
    PostInvestmentMonitor,
    BasisAlertConfig,
    UnhedgedAlertConfig,
)
from app.models.alert_history import BasisAlertRecord, BasisAlertHistory
from app.models.market_data import OISnapshot
from app.utils.auth import require_auth

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/alert", tags=["alert"])


# ==================== Schemas ====================

# --- Lark Bot ---

class LarkBotCreate(BaseModel):
    name: str
    webhook_url: str

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be empty")
        if len(v) > 100:
            raise ValueError("Name must be at most 100 characters")
        return v

    @field_validator("webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Webhook URL cannot be empty")
        if not v.startswith("http"):
            raise ValueError("Webhook URL must start with http")
        return v


class LarkBotUpdate(BaseModel):
    name: Optional[str] = None
    webhook_url: Optional[str] = None


class LarkBotResponse(BaseModel):
    id: int
    name: str
    webhook_url: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- Post-Investment Monitor ---

class MonitorCreate(BaseModel):
    coin_name: str
    long_exchange: str
    short_exchange: str
    spread_threshold: Optional[float] = None
    price_threshold: Optional[float] = None
    oi_drop_1h_threshold: Optional[float] = None
    oi_drop_4h_threshold: Optional[float] = None
    sound_enabled: bool = True
    popup_enabled: bool = True
    lark_bot_id: Optional[int] = None

    @field_validator("coin_name")
    @classmethod
    def validate_coin_name(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("Coin name cannot be empty")
        return v


class MonitorUpdate(BaseModel):
    coin_name: Optional[str] = None
    long_exchange: Optional[str] = None
    short_exchange: Optional[str] = None
    spread_threshold: Optional[float] = None
    price_threshold: Optional[float] = None
    oi_drop_1h_threshold: Optional[float] = None
    oi_drop_4h_threshold: Optional[float] = None
    sound_enabled: Optional[bool] = None
    popup_enabled: Optional[bool] = None
    lark_bot_id: Optional[int] = None


class MonitorResponse(BaseModel):
    id: int
    coin_name: str
    long_exchange: str
    short_exchange: str
    spread_threshold: Optional[float]
    price_threshold: Optional[float]
    oi_drop_1h_threshold: Optional[float]
    oi_drop_4h_threshold: Optional[float]
    sound_enabled: bool
    popup_enabled: bool
    lark_bot_id: Optional[int]
    is_active: bool
    created_at: datetime
    updated_at: datetime
    # Real-time values (enriched at query time)
    current_spread: Optional[float] = None
    current_price: Optional[float] = None
    current_oi_drop_1h: Optional[float] = None
    current_oi_drop_4h: Optional[float] = None

    model_config = {"from_attributes": True}


# --- Basis Alert Config ---

class BasisConfigUpdate(BaseModel):
    basis_threshold: Optional[float] = None
    expand_multiplier: Optional[float] = None
    clear_interval_hours: Optional[int] = None
    blocked_coins: Optional[List[str]] = None
    sound_enabled: Optional[bool] = None
    popup_enabled: Optional[bool] = None
    lark_bot_id: Optional[int] = None

    @field_validator("clear_interval_hours")
    @classmethod
    def validate_clear_interval(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 1:
            raise ValueError("clear_interval_hours must be at least 1")
        return v


class BasisConfigResponse(BaseModel):
    id: int
    basis_threshold: float
    expand_multiplier: float
    clear_interval_hours: int
    blocked_coins: Optional[List[str]]
    sound_enabled: bool
    popup_enabled: bool
    lark_bot_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("blocked_coins", mode="before")
    @classmethod
    def parse_blocked_coins(cls, v: Optional[str]) -> Optional[List[str]]:
        if v is None or v == "":
            return []
        if isinstance(v, list):
            return v
        return [c.strip() for c in v.split(",") if c.strip()]


class BasisHistoryResponse(BaseModel):
    id: int
    coin_name: str
    alert_type: str
    basis_value: float
    alert_at: datetime

    model_config = {"from_attributes": True}


# --- Unhedged Alert Config ---

class UnhedgedConfigUpdate(BaseModel):
    sound_enabled: Optional[bool] = None
    popup_enabled: Optional[bool] = None
    lark_bot_id: Optional[int] = None


class UnhedgedConfigResponse(BaseModel):
    id: int
    sound_enabled: bool
    popup_enabled: bool
    lark_bot_id: Optional[int]

    model_config = {"from_attributes": True}


# --- Generic ---

class MessageResponse(BaseModel):
    message: str


# ==================== Lark Bot Endpoints ====================

@router.get("/lark-bots", response_model=List[LarkBotResponse])
async def get_lark_bots(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get all Lark bots for current user."""
    result = await db.execute(
        select(LarkBot).where(LarkBot.user_id == user.id).order_by(LarkBot.created_at.desc())
    )
    bots = result.scalars().all()
    return bots


@router.post("/lark-bots", response_model=LarkBotResponse, status_code=status.HTTP_201_CREATED)
async def create_lark_bot(
    body: LarkBotCreate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Create a new Lark bot."""
    bot = LarkBot(
        user_id=user.id,
        name=body.name,
        webhook_url=body.webhook_url,
    )
    db.add(bot)
    await db.flush()
    await db.refresh(bot)
    return bot


@router.put("/lark-bots/{bot_id}", response_model=LarkBotResponse)
async def update_lark_bot(
    bot_id: int,
    body: LarkBotUpdate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update a Lark bot."""
    result = await db.execute(
        select(LarkBot).where(LarkBot.id == bot_id, LarkBot.user_id == user.id)
    )
    bot = result.scalar_one_or_none()
    if bot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lark bot not found")

    if body.name is not None:
        bot.name = body.name
    if body.webhook_url is not None:
        bot.webhook_url = body.webhook_url

    await db.flush()
    await db.refresh(bot)
    return bot


@router.delete("/lark-bots/{bot_id}", response_model=MessageResponse)
async def delete_lark_bot(
    bot_id: int,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Delete a Lark bot."""
    result = await db.execute(
        select(LarkBot).where(LarkBot.id == bot_id, LarkBot.user_id == user.id)
    )
    bot = result.scalar_one_or_none()
    if bot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lark bot not found")

    await db.delete(bot)
    await db.flush()
    return MessageResponse(message="Lark bot deleted")


# ==================== Post-Investment Monitor Endpoints ====================


@router.get("/post-investment/available-coins")
async def get_available_coins(user: User = Depends(require_auth)):
    """Return available coins and their exchange pairs from cached API data."""
    from app.services.data_fetcher import data_fetcher

    cached = data_fetcher.get_cached_data()
    # {coin_name: [{long_exchange, short_exchange}, ...]}
    coins: Dict[str, List[Dict[str, str]]] = {}
    for pair_key, pair_data in cached.items():
        if not pair_data or not isinstance(pair_data, dict):
            continue
        items = pair_data.get("data", pair_data)
        if isinstance(items, dict):
            items = items.get("data", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            coin_name = (
                item.get("symbolName", "")
                or item.get("coinName", "")
                or item.get("coin_name", "")
            )
            if not coin_name:
                continue
            long_ex = item.get("longExchange", "")
            short_ex = item.get("shortExchange", "")
            if not long_ex or not short_ex:
                continue
            pair = {"long_exchange": long_ex.upper(), "short_exchange": short_ex.upper()}
            coin_key = coin_name.upper()
            if coin_key not in coins:
                coins[coin_key] = []
            # Deduplicate
            if pair not in coins[coin_key]:
                coins[coin_key].append(pair)
    return coins


@router.get("/post-investment", response_model=List[MonitorResponse])
async def get_monitors(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get all post-investment monitors for current user. Active ones first."""
    from app.services.data_fetcher import data_fetcher
    from app.services.alert_engine import alert_engine

    result = await db.execute(
        select(PostInvestmentMonitor)
        .where(PostInvestmentMonitor.user_id == user.id)
        .order_by(PostInvestmentMonitor.is_active.desc(), PostInvestmentMonitor.created_at.desc())
    )
    monitors = result.scalars().all()

    # Build real-time data lookup from cached API data
    cached = data_fetcher.get_cached_data()
    coin_data: dict = {}
    for pair_key, pair_data in cached.items():
        if not pair_data or not isinstance(pair_data, dict):
            continue
        items = pair_data.get("data", pair_data)
        if isinstance(items, dict):
            items = items.get("data", [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            coin_name = (
                item.get("symbolName", "")
                or item.get("coinName", "")
                or item.get("coin_name", "")
            )
            if not coin_name:
                continue
            long_ex = item.get(
                "longExchange",
                pair_key.split("_")[0] if "_" in pair_key else "",
            )
            short_ex = item.get(
                "shortExchange",
                pair_key.split("_")[1] if "_" in pair_key else "BINANCE",
            )
            key = f"{coin_name.upper()}_{long_ex.upper()}_{short_ex.upper()}"
            coin_data[key] = item

    oi_cache = alert_engine.get_oi_cache()

    # Enrich each monitor with real-time values
    enriched = []
    for m in monitors:
        resp = MonitorResponse.model_validate(m)
        lookup_key = f"{m.coin_name.upper()}_{m.long_exchange.upper()}_{m.short_exchange.upper()}"
        item = coin_data.get(lookup_key)
        if item:
            try:
                bid = float(item.get("bid", 0) or 0)
                ask = float(item.get("ask", 0) or 0)
                if bid > 0:
                    resp.current_spread = round((ask - bid) / bid * 100, 4)
                    resp.current_price = round(bid, 4)
            except (ValueError, TypeError):
                pass
        # OI from cache
        coin_oi = oi_cache.get(m.coin_name.upper(), {})
        if coin_oi.get("1h") is not None:
            resp.current_oi_drop_1h = coin_oi["1h"]
        if coin_oi.get("4h") is not None:
            resp.current_oi_drop_4h = coin_oi["4h"]
        enriched.append(resp)

    return enriched


@router.post("/post-investment", response_model=MonitorResponse, status_code=status.HTTP_201_CREATED)
async def create_monitor(
    body: MonitorCreate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Create new post-investment monitor."""
    # Validate lark_bot_id ownership if provided
    if body.lark_bot_id is not None:
        bot_result = await db.execute(
            select(LarkBot).where(LarkBot.id == body.lark_bot_id, LarkBot.user_id == user.id)
        )
        if bot_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lark bot not found or not owned by you",
            )

    monitor = PostInvestmentMonitor(
        user_id=user.id,
        coin_name=body.coin_name,
        long_exchange=body.long_exchange,
        short_exchange=body.short_exchange,
        spread_threshold=body.spread_threshold,
        price_threshold=body.price_threshold,
        oi_drop_1h_threshold=body.oi_drop_1h_threshold,
        oi_drop_4h_threshold=body.oi_drop_4h_threshold,
        sound_enabled=body.sound_enabled,
        popup_enabled=body.popup_enabled,
        lark_bot_id=body.lark_bot_id,
    )
    db.add(monitor)
    # Reset OI data for this user+symbol
    symbol = f"{body.coin_name.upper()}USDT"
    await db.execute(
        delete(OISnapshot).where(
            OISnapshot.user_id == user.id,
            OISnapshot.symbol == symbol,
        )
    )
    await db.flush()
    await db.refresh(monitor)
    return monitor


@router.put("/post-investment/{monitor_id}", response_model=MonitorResponse)
async def update_monitor(
    monitor_id: int,
    body: MonitorUpdate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update a post-investment monitor."""
    result = await db.execute(
        select(PostInvestmentMonitor).where(
            PostInvestmentMonitor.id == monitor_id,
            PostInvestmentMonitor.user_id == user.id,
        )
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    update_data = body.dict(exclude_unset=True)

    # Validate lark_bot_id ownership if being updated
    if "lark_bot_id" in update_data and update_data["lark_bot_id"] is not None:
        bot_result = await db.execute(
            select(LarkBot).where(
                LarkBot.id == update_data["lark_bot_id"], LarkBot.user_id == user.id
            )
        )
        if bot_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lark bot not found or not owned by you",
            )

    old_coin = monitor.coin_name
    for key, value in update_data.items():
        setattr(monitor, key, value)
    new_coin = monitor.coin_name

    # Reset OI data on any update
    for coin in {old_coin, new_coin}:
        symbol = f"{coin.upper()}USDT"
        await db.execute(
            delete(OISnapshot).where(
                OISnapshot.user_id == user.id,
                OISnapshot.symbol == symbol,
            )
        )

    await db.flush()
    await db.refresh(monitor)
    return monitor


@router.patch("/post-investment/{monitor_id}/toggle", response_model=MonitorResponse)
async def toggle_monitor(
    monitor_id: int,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Toggle monitor active/inactive."""
    result = await db.execute(
        select(PostInvestmentMonitor).where(
            PostInvestmentMonitor.id == monitor_id,
            PostInvestmentMonitor.user_id == user.id,
        )
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    monitor.is_active = not monitor.is_active
    await db.flush()
    await db.refresh(monitor)
    return monitor


@router.delete("/post-investment/{monitor_id}", response_model=MessageResponse)
async def delete_monitor(
    monitor_id: int,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Delete a post-investment monitor."""
    result = await db.execute(
        select(PostInvestmentMonitor).where(
            PostInvestmentMonitor.id == monitor_id,
            PostInvestmentMonitor.user_id == user.id,
        )
    )
    monitor = result.scalar_one_or_none()
    if monitor is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Monitor not found")

    # Clean up OI data
    symbol = f"{monitor.coin_name.upper()}USDT"
    await db.execute(
        delete(OISnapshot).where(
            OISnapshot.user_id == user.id,
            OISnapshot.symbol == symbol,
        )
    )
    await db.delete(monitor)
    await db.flush()
    return MessageResponse(message="Monitor deleted")


# ==================== Basis Alert Config Endpoints ====================

@router.get("/basis", response_model=BasisConfigResponse)
async def get_basis_config(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get basis alert config. Create default if not exists."""
    result = await db.execute(
        select(BasisAlertConfig).where(BasisAlertConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if config is None:
        config = BasisAlertConfig(user_id=user.id)
        db.add(config)
        await db.flush()
        await db.refresh(config)

    return config


@router.put("/basis", response_model=BasisConfigResponse)
async def update_basis_config(
    body: BasisConfigUpdate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update basis alert config."""
    result = await db.execute(
        select(BasisAlertConfig).where(BasisAlertConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if config is None:
        config = BasisAlertConfig(user_id=user.id)
        db.add(config)
        await db.flush()
        await db.refresh(config)

    # Validate lark_bot_id ownership if provided
    if body.lark_bot_id is not None:
        bot_result = await db.execute(
            select(LarkBot).where(LarkBot.id == body.lark_bot_id, LarkBot.user_id == user.id)
        )
        if bot_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lark bot not found or not owned by you",
            )

    update_data = body.dict(exclude_unset=True)

    # Handle blocked_coins: convert list to comma-separated string
    if "blocked_coins" in update_data:
        coins = update_data["blocked_coins"]
        if coins is None:
            config.blocked_coins = None
        else:
            config.blocked_coins = ",".join(coins)
        del update_data["blocked_coins"]

    for key, value in update_data.items():
        setattr(config, key, value)

    await db.flush()
    await db.refresh(config)

    # Invalidate basis alert scheduler config cache
    from app.schedulers.basis_alert_scheduler import basis_alert_scheduler
    basis_alert_scheduler.invalidate_config()

    return config


@router.get("/basis/history", response_model=List[BasisHistoryResponse])
async def get_basis_history(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get basis alert history for current user."""
    result = await db.execute(
        select(BasisAlertHistory)
        .where(BasisAlertHistory.user_id == user.id)
        .order_by(BasisAlertHistory.alert_at.desc())
        .limit(200)
    )
    history = result.scalars().all()
    return history


@router.post("/basis/clear", response_model=MessageResponse)
async def clear_basis_data(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Clear basis alert records + blocked coins. Keep other config."""
    # Delete alert records for this user
    await db.execute(
        delete(BasisAlertRecord).where(BasisAlertRecord.user_id == user.id)
    )
    # Delete alert history for this user
    await db.execute(
        delete(BasisAlertHistory).where(BasisAlertHistory.user_id == user.id)
    )
    # Clear blocked coins in config
    result = await db.execute(
        select(BasisAlertConfig).where(BasisAlertConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if config is not None:
        config.blocked_coins = None

    await db.flush()
    return MessageResponse(message="Basis alert data cleared")


# ==================== Unhedged Alert Config Endpoints ====================

@router.get("/unhedged", response_model=UnhedgedConfigResponse)
async def get_unhedged_config(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get unhedged alert config. Create default if not exists."""
    result = await db.execute(
        select(UnhedgedAlertConfig).where(UnhedgedAlertConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if config is None:
        config = UnhedgedAlertConfig(user_id=user.id)
        db.add(config)
        await db.flush()
        await db.refresh(config)

    return config


@router.put("/unhedged", response_model=UnhedgedConfigResponse)
async def update_unhedged_config(
    body: UnhedgedConfigUpdate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update unhedged alert config."""
    result = await db.execute(
        select(UnhedgedAlertConfig).where(UnhedgedAlertConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if config is None:
        config = UnhedgedAlertConfig(user_id=user.id)
        db.add(config)
        await db.flush()
        await db.refresh(config)

    # Validate lark_bot_id ownership if provided
    if body.lark_bot_id is not None:
        bot_result = await db.execute(
            select(LarkBot).where(LarkBot.id == body.lark_bot_id, LarkBot.user_id == user.id)
        )
        if bot_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Lark bot not found or not owned by you",
            )

    update_data = body.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)

    await db.flush()
    await db.refresh(config)
    return config


# ==================== New Listing Alerts ====================

class NewListingAlertConfigCreate(BaseModel):
    sound_enabled: bool = True
    popup_enabled: bool = True
    lark_bot_id: Optional[int] = None


@router.get("/new-listing/config")
async def get_new_listing_config(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get user's new listing alert config."""
    from app.models.alert_config import NewListingAlertConfig
    result = await db.execute(
        select(NewListingAlertConfig).where(NewListingAlertConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        return {
            "data": {
                "sound_enabled": True,
                "popup_enabled": True,
                "lark_bot_id": None,
            }
        }
    return {
        "data": {
            "sound_enabled": config.sound_enabled,
            "popup_enabled": config.popup_enabled,
            "lark_bot_id": config.lark_bot_id,
        }
    }


@router.put("/new-listing/config")
async def update_new_listing_config(
    body: NewListingAlertConfigCreate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update user's new listing alert config."""
    from app.models.alert_config import NewListingAlertConfig

    # Validate lark_bot_id belongs to user
    if body.lark_bot_id:
        bot = await db.execute(
            select(LarkBot).where(LarkBot.id == body.lark_bot_id, LarkBot.user_id == user.id)
        )
        if not bot.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="机器人不存在")

    result = await db.execute(
        select(NewListingAlertConfig).where(NewListingAlertConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if config:
        config.sound_enabled = body.sound_enabled
        config.popup_enabled = body.popup_enabled
        config.lark_bot_id = body.lark_bot_id
    else:
        config = NewListingAlertConfig(
            user_id=user.id,
            sound_enabled=body.sound_enabled,
            popup_enabled=body.popup_enabled,
            lark_bot_id=body.lark_bot_id,
        )
        db.add(config)

    await db.flush()
    return {"status": "ok"}


@router.get("/new-listing/alerts")
async def get_new_listing_alerts(
    user: User = Depends(require_auth),
):
    """Get new listing alert history."""
    from app.schedulers.new_listing_scheduler import new_listing_scheduler
    return {"data": new_listing_scheduler.get_alerts()}


# ==================== Funding Break Alerts ====================

class FundingBreakAlertConfigCreate(BaseModel):
    sound_enabled: bool = True
    popup_enabled: bool = True
    lark_bot_id: Optional[int] = None


@router.get("/funding-break/config")
async def get_funding_break_config(
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Get user's funding break alert config."""
    from app.models.alert_config import FundingBreakAlertConfig
    result = await db.execute(
        select(FundingBreakAlertConfig).where(FundingBreakAlertConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()
    if not config:
        return {"data": {"sound_enabled": True, "popup_enabled": True, "lark_bot_id": None}}
    return {
        "data": {
            "sound_enabled": config.sound_enabled,
            "popup_enabled": config.popup_enabled,
            "lark_bot_id": config.lark_bot_id,
        }
    }


@router.put("/funding-break/config")
async def update_funding_break_config(
    body: FundingBreakAlertConfigCreate,
    user: User = Depends(require_auth),
    db: AsyncSession = Depends(get_db),
):
    """Update user's funding break alert config."""
    from app.models.alert_config import FundingBreakAlertConfig

    if body.lark_bot_id:
        bot = await db.execute(
            select(LarkBot).where(LarkBot.id == body.lark_bot_id, LarkBot.user_id == user.id)
        )
        if not bot.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="机器人不存在")

    result = await db.execute(
        select(FundingBreakAlertConfig).where(FundingBreakAlertConfig.user_id == user.id)
    )
    config = result.scalar_one_or_none()

    if config:
        config.sound_enabled = body.sound_enabled
        config.popup_enabled = body.popup_enabled
        config.lark_bot_id = body.lark_bot_id
    else:
        config = FundingBreakAlertConfig(
            user_id=user.id,
            sound_enabled=body.sound_enabled,
            popup_enabled=body.popup_enabled,
            lark_bot_id=body.lark_bot_id,
        )
        db.add(config)

    await db.flush()
    return {"status": "ok"}


@router.get("/funding-break/alerts")
async def get_funding_break_alerts(
    user: User = Depends(require_auth),
):
    """Get funding break alert history."""
    from app.services.funding_break import funding_break_service
    return {"data": funding_break_service.get_alert_history()}
