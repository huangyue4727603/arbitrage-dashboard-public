import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.services.funding_rank import FundingRankService
from app.schedulers.funding_scheduler import funding_rank_scheduler
from app.schedulers.kline_scheduler import kline_scheduler
from app.services.data_fetcher import data_fetcher
from app.schedulers.oi_lsr_scheduler import oi_lsr_scheduler
from app.utils.auth import get_optional_user_id

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


@router.get("/index-overlap")
async def get_index_overlap():
    """Return index-constituent overlap percentage using normalized spot_exchange names."""
    from sqlalchemy import text
    from app.database import async_session_factory

    sql = text("""
        SELECT a.coin, a.exchange AS ex_a, b.exchange AS ex_b,
               SUM(LEAST(a.weight, b.weight)) AS overlap
        FROM arb_index_constituents a
        JOIN arb_spot_exchange_mapping ma ON a.spot_exchange = ma.raw_name
        JOIN arb_index_constituents b
          ON a.coin = b.coin
         AND a.exchange <> b.exchange
        JOIN arb_spot_exchange_mapping mb ON b.spot_exchange = mb.raw_name
        WHERE ma.normalized_name = mb.normalized_name
        GROUP BY a.coin, a.exchange, b.exchange
    """)
    out: dict = {}
    async with async_session_factory() as db:
        r = await db.execute(sql)
        for coin, ex_a, ex_b, overlap in r.all():
            out[f"{coin}_{ex_a}_{ex_b}"] = round(float(overlap or 0), 4)
    return {"data": out}


@router.get("/index-detail")
async def get_index_detail(coin: str, long_exchange: str, short_exchange: str):
    """Return detailed index constituents for a coin on two exchanges, with normalized names.

    Groups by normalized spot_exchange, shows weight from each exchange side by side.
    """
    from sqlalchemy import text
    from app.database import async_session_factory

    # Exchange key to DB exchange column mapping
    ex_map = {"BN": "BN", "OKX": "OKX", "BY": "BY"}
    long_ex = ex_map.get(long_exchange, long_exchange)
    short_ex = ex_map.get(short_exchange, short_exchange)

    sql = text("""
        SELECT
            COALESCE(m.normalized_name, c.spot_exchange) AS norm_exchange,
            c.exchange,
            SUM(c.weight) AS weight
        FROM arb_index_constituents c
        LEFT JOIN arb_spot_exchange_mapping m ON c.spot_exchange = m.raw_name
        WHERE c.coin = :coin AND c.exchange IN (:long_ex, :short_ex)
        GROUP BY norm_exchange, c.exchange
        ORDER BY norm_exchange
    """)

    async with async_session_factory() as db:
        r = await db.execute(sql, {"coin": coin.upper(), "long_ex": long_ex, "short_ex": short_ex})
        rows = r.all()

    # Build: {norm_exchange: {long_weight, short_weight}}
    detail: dict[str, dict] = {}
    for norm, exchange, weight in rows:
        if norm not in detail:
            detail[norm] = {"exchange": norm, "long_weight": 0, "short_weight": 0}
        if exchange == long_ex:
            detail[norm]["long_weight"] = round(float(weight or 0), 4)
        elif exchange == short_ex:
            detail[norm]["short_weight"] = round(float(weight or 0), 4)

    # Mark common (both > 0)
    result = []
    for item in sorted(detail.values(), key=lambda x: -(min(x["long_weight"], x["short_weight"]))):
        item["common"] = item["long_weight"] > 0 and item["short_weight"] > 0
        result.append(item)

    return {"data": result, "coin": coin.upper(),
            "long_exchange": long_exchange, "short_exchange": short_exchange}


@router.get("/bn-index-weights")
async def get_bn_index_weights():
    """Return binance_alpha and binance_future weights per coin from BN index constituents.

    Response: {"RAVE": {"alpha": 0.1333, "future": 0.2}, "SIREN": {"alpha": 0.5, "future": 0.125}, ...}
    """
    from sqlalchemy import text
    from app.database import async_session_factory

    sql = text("""
        SELECT coin, spot_exchange, weight
        FROM arb_index_constituents
        WHERE exchange = 'BN'
          AND spot_exchange IN ('binance_alpha', 'binance_future')
    """)
    out: dict = {}
    async with async_session_factory() as db:
        r = await db.execute(sql)
        for coin, spot_ex, weight in r.all():
            if coin not in out:
                out[coin] = {}
            if spot_ex == "binance_alpha":
                out[coin]["alpha"] = round(float(weight or 0), 4)
            elif spot_ex == "binance_future":
                out[coin]["future"] = round(float(weight or 0), 4)
    return {"data": out}


@router.get("/oi-lsr")
async def get_oi_lsr():
    """Return latest OI (USDT) and Long/Short Ratio per symbol."""
    oi = oi_lsr_scheduler.get_latest_oi()
    lsr = oi_lsr_scheduler.get_latest_lsr()
    # Merge into {coin: {oi, lsr}}
    result: dict[str, dict] = {}
    for symbol, val in oi.items():
        coin = symbol[:-4] if symbol.endswith("USDT") else symbol
        result[coin] = {"oi": val}
    for symbol, val in lsr.items():
        coin = symbol[:-4] if symbol.endswith("USDT") else symbol
        if coin in result:
            result[coin]["lsr"] = val
        else:
            result[coin] = {"lsr": val}
    return {"data": result}


@router.get("/bn-spot")
async def get_bn_spot():
    """Return set of coins that have Binance USDT spot trading pairs."""
    from sqlalchemy import select as sa_select
    from app.database import async_session_factory
    from app.models.market_data import BnSpotSymbol

    async with async_session_factory() as db:
        result = await db.execute(sa_select(BnSpotSymbol.coin))
        coins = [row[0] for row in result.all()]
    return {"data": coins}


@router.get("/watchlist")
async def get_watchlist(user_id: Optional[int] = Depends(get_optional_user_id)):
    """Get user's watched items as list of 'COIN_LONGEX_SHORTEX' keys."""
    if not user_id:
        return {"data": []}
    from sqlalchemy import select as sa_select
    from app.database import async_session_factory
    from app.models.market_data import UserWatchlist
    async with async_session_factory() as db:
        result = await db.execute(
            sa_select(UserWatchlist.coin, UserWatchlist.long_exchange, UserWatchlist.short_exchange)
            .where(UserWatchlist.user_id == user_id)
        )
        return {"data": [f"{r[0]}_{r[1]}_{r[2]}" for r in result.all()]}


class WatchlistBody(BaseModel):
    coin: str
    long_exchange: str
    short_exchange: str


@router.post("/watchlist")
async def add_watchlist(body: WatchlistBody, user_id: Optional[int] = Depends(get_optional_user_id)):
    """Add a coin+exchange pair to user's watchlist."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required")
    from sqlalchemy.dialects.mysql import insert as mysql_insert
    from app.database import async_session_factory
    from app.models.market_data import UserWatchlist
    async with async_session_factory() as db:
        stmt = mysql_insert(UserWatchlist).values(
            user_id=user_id, coin=body.coin.upper(),
            long_exchange=body.long_exchange, short_exchange=body.short_exchange,
        )
        stmt = stmt.on_duplicate_key_update(coin=stmt.inserted.coin)
        await db.execute(stmt)
        await db.commit()
    return {"ok": True}


@router.delete("/watchlist")
async def remove_watchlist(body: WatchlistBody, user_id: Optional[int] = Depends(get_optional_user_id)):
    """Remove a coin+exchange pair from user's watchlist."""
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required")
    from sqlalchemy import delete as sa_delete
    from app.database import async_session_factory
    from app.models.market_data import UserWatchlist
    async with async_session_factory() as db:
        await db.execute(
            sa_delete(UserWatchlist)
            .where(UserWatchlist.user_id == user_id)
            .where(UserWatchlist.coin == body.coin.upper())
            .where(UserWatchlist.long_exchange == body.long_exchange)
            .where(UserWatchlist.short_exchange == body.short_exchange)
        )
        await db.commit()
    return {"ok": True}


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
