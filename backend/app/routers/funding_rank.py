import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.services.funding_rank import FundingRankService
from app.schedulers.funding_scheduler import funding_rank_scheduler
from app.schedulers.kline_scheduler import kline_scheduler
from app.services.data_fetcher import data_fetcher

router = APIRouter(prefix="/api/funding-rank", tags=["funding-rank"])

service = FundingRankService()

# Mapping: data_fetcher pair key -> (short_long_ex, short_short_ex)
_PAIR_MAP = {
    "BYBIT_BINANCE": ("BY", "BN"),
    "OKX_BINANCE": ("OKX", "BN"),
    "OKX_BYBIT": ("OKX", "BY"),
    "BINANCE_OKX": ("BN", "OKX"),
    "BINANCE_BYBIT": ("BN", "BY"),
    "BYBIT_OKX": ("BY", "OKX"),
}


class CalculatorRequest(BaseModel):
    coin: str
    long_exchange: str
    short_exchange: str
    start: Optional[int] = None
    end: Optional[int] = None


def _get_active_coins() -> set[str]:
    """Get set of active coin keys (coin_longEx_shortEx) from realtime API data."""
    cached = data_fetcher.get_cached_data()
    active: set[str] = set()
    for pair_key, pair_data in cached.items():
        if not pair_data or not isinstance(pair_data, dict):
            continue
        long_ex, short_ex = _PAIR_MAP.get(pair_key, (None, None))
        if not long_ex:
            continue
        items = pair_data.get("data", pair_data)
        if isinstance(items, dict):
            items = items.get("data", [])
        if not isinstance(items, list):
            continue
        for item in items:
            coin = item.get("coinName", "") or item.get("symbolName", "")
            if not coin:
                continue
            if coin.endswith("USDT"):
                coin = coin[:-4]
            active.add(f"{coin}_{long_ex}_{short_ex}")
    return active


def _filter_rankings(data: list, long_exchange: Optional[str], short_exchange: Optional[str]) -> list:
    """Filter rankings by exchange and active coins."""
    # Filter to only active coins (those with realtime API data)
    active = _get_active_coins()
    if active:
        data = [r for r in data if f"{r['coin']}_{r['long_exchange']}_{r['short_exchange']}" in active]
    if long_exchange:
        data = [r for r in data if r["long_exchange"] == long_exchange]
    if short_exchange:
        data = [r for r in data if r["short_exchange"] == short_exchange]
    return data


@router.get("")
async def get_rankings(
    start: Optional[int] = None,
    end: Optional[int] = None,
    long_exchange: Optional[str] = None,
    short_exchange: Optional[str] = None,
):
    """Get unified ranking list. Uses scheduler cache for default 24h, computes from DB for custom range."""
    now_ms = int(time.time() * 1000)

    # Default 24h: return scheduler cache
    if start is None and end is None:
        cached = funding_rank_scheduler.get_cached_rankings()
        if cached["data"] is not None:
            data = _filter_rankings(cached["data"], long_exchange, short_exchange)
            return {"data": data, "start": cached["start"], "end": cached["end"]}

    if end is None:
        end = now_ms
    if start is None:
        start = end - 24 * 60 * 60 * 1000

    if start >= end:
        raise HTTPException(status_code=400, detail="start must be less than end")

    # Compute from DB for any time range
    data = await service.get_rankings(start, end)
    data = _filter_rankings(data, long_exchange, short_exchange)

    return {"data": data, "start": start, "end": end}


@router.get("/realtime")
async def get_realtime():
    """Get current spread and basis for all coins from realtime API data (updated every 3s)."""
    cached = data_fetcher.get_cached_data()
    result = {}

    for pair_key, pair_data in cached.items():
        if not pair_data or not isinstance(pair_data, dict):
            continue
        long_ex, short_ex = _PAIR_MAP.get(pair_key, (None, None))
        if not long_ex:
            continue

        items = pair_data.get("data", pair_data)
        if isinstance(items, dict):
            items = items.get("data", [])
        if not isinstance(items, list):
            continue

        for item in items:
            coin = item.get("coinName", "") or item.get("symbolName", "")
            if not coin:
                continue
            if coin.endswith("USDT"):
                coin = coin[:-4]

            bid = float(item.get("bid", 0) or 0)
            ask = float(item.get("ask", 0) or 0)
            basis = float(item.get("shortPremium", 0) or 0)

            spread = round((ask - bid) / bid * 100, 4) if bid > 0 else 0.0

            key = f"{coin}_{long_ex}_{short_ex}"
            result[key] = {
                "spread": spread,
                "basis": round(basis * 100, 4),
            }

    return {"data": result}


@router.get("/price-changes")
async def get_price_changes():
    """Get cached 1d/3d price changes (updated every 5 minutes by kline scheduler)."""
    return {"data": kline_scheduler.get_price_changes()}


@router.get("/coins")
async def get_coins():
    """Get list of all coins available in funding history."""
    from sqlalchemy import distinct, select as sa_select
    from app.database import async_session_factory
    from app.models.market_data import FundingHistory

    async with async_session_factory() as db:
        result = await db.execute(sa_select(distinct(FundingHistory.coin)).order_by(FundingHistory.coin))
        coins = [row[0] for row in result.all()]
    return {"data": coins}


@router.get("/detail")
async def get_detail(
    coin: str,
    long_exchange: str,
    short_exchange: str,
    start: Optional[int] = None,
    end: Optional[int] = None,
):
    """Get per-period funding detail from DB."""
    now_ms = int(time.time() * 1000)
    if end is None:
        end = now_ms
    if start is None:
        start = end - 24 * 60 * 60 * 1000

    if start >= end:
        raise HTTPException(status_code=400, detail="start must be less than end")

    valid_exchanges = {"BN", "OKX", "BY"}
    if long_exchange not in valid_exchanges or short_exchange not in valid_exchanges:
        raise HTTPException(status_code=400, detail="Invalid exchange. Use BN, OKX, or BY")

    details = await service.get_funding_detail(
        coin.upper(), long_exchange, short_exchange, start, end
    )
    return {"data": details}


@router.post("/calculator")
async def calculate(body: CalculatorRequest):
    """Funding calculator tool - computes from DB."""
    now_ms = int(time.time() * 1000)
    end = body.end if body.end is not None else now_ms
    start = body.start if body.start is not None else end - 24 * 60 * 60 * 1000

    if start >= end:
        raise HTTPException(status_code=400, detail="start must be less than end")

    valid_exchanges = {"BN", "OKX", "BY"}
    if body.long_exchange not in valid_exchanges or body.short_exchange not in valid_exchanges:
        raise HTTPException(status_code=400, detail="Invalid exchange. Use BN, OKX, or BY")

    result = await service.calculate_statistics(
        body.coin.upper(), body.long_exchange, body.short_exchange, start, end
    )
    return {"data": result}
