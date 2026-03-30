import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
from fastapi import APIRouter, Query
from sqlalchemy import select, func

from app.config import get_settings
from app.database import async_session_factory
from app.models.market_data import FundingHistory
from app.services.exchange.binance import BinanceClient

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/premium-filter", tags=["premium-filter"])

settings = get_settings()
SELF_API_URL = settings.ARBITRAGE_API_URL

# Binance premiumIndex cache (all symbols, refreshed every 10s)
_bn_premium_cache: Dict[str, float] = {}
_bn_premium_ts: float = 0
_BN_PREMIUM_TTL = 30  # seconds, avoid frequent Binance API calls


async def _get_binance_premium() -> Dict[str, float]:
    """Get Binance premium index for all symbols, cached for 10s."""
    global _bn_premium_cache, _bn_premium_ts

    now = time.time()
    if _bn_premium_cache and (now - _bn_premium_ts) < _BN_PREMIUM_TTL:
        return _bn_premium_cache

    try:
        async with BinanceClient() as client:
            data = await client.get_premium_index(timeout=10)

        result: Dict[str, float] = {}
        if isinstance(data, list):
            for item in data:
                symbol = item.get("symbol", "")
                if not symbol.endswith("USDT"):
                    continue
                mark = float(item.get("markPrice", 0))
                index = float(item.get("indexPrice", 0))
                if index > 0:
                    coin = symbol[:-4]
                    basis_pct = round((mark - index) / index * 100, 4)
                    result[coin] = basis_pct

        _bn_premium_cache = result
        _bn_premium_ts = now
        logger.info("Binance premiumIndex cached: %d symbols", len(result))
        return result
    except Exception as exc:
        logger.error("Failed to fetch Binance premiumIndex: %s", exc)
        return _bn_premium_cache  # Return stale cache on error


@router.get("")
async def get_premium_filter(
    ts: int = Query(..., description="Timestamp in milliseconds"),
    premiumThreshold: float = Query(..., description="Minimum premium threshold (e.g. -0.02)"),
):
    """Proxy to self-hosted premium_filter API, parse coin names, and enrich with funding + basis data."""
    timeout = aiohttp.ClientTimeout(total=30, sock_read=15)
    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            async with session.get(
                f"{SELF_API_URL}/api/v1/arbitrage/chance/premium_filter",
                params={"ts": ts, "premiumThreshold": premiumThreshold},
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()

        raw_list = body.get("data", [])
        # Parse "BINANCE_G-USDT-PERP" -> extract coin name
        coins: List[dict] = []
        seen: set = set()
        for item in raw_list:
            match = re.match(r"^([A-Z]+)_(.+?)-USDT?C?-", item)
            if match:
                exchange = match.group(1)
                coin = match.group(2)
                if coin not in seen:
                    seen.add(coin)
                    coins.append({"coin_name": coin, "exchange": exchange, "raw": item})

        if not coins:
            return {"data": []}

        # Enrich with cumulative funding from DB (Binance only, from ts to now)
        start_time = datetime.utcfromtimestamp(ts / 1000)
        coin_names = [c["coin_name"] for c in coins]

        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(
                        FundingHistory.coin,
                        func.sum(FundingHistory.funding_rate).label("total"),
                    )
                    .where(FundingHistory.exchange == "BN")
                    .where(FundingHistory.funding_time >= start_time)
                    .where(FundingHistory.coin.in_(coin_names))
                    .group_by(FundingHistory.coin)
                )
                funding_map = {row[0]: round(row[1] * 100, 3) for row in result.all()}
        except Exception as exc:
            logger.error("Failed to query funding cumulative: %s", exc)
            funding_map = {}

        # Get settlement periods from FundingCap table
        interval_map: Dict[str, int] = {}
        try:
            from app.models.market_data import FundingCap
            async with async_session_factory() as db:
                result = await db.execute(
                    select(FundingCap.symbol, FundingCap.interval_hours)
                    .where(FundingCap.exchange == "Binance")
                )
                for row in result.all():
                    sym = row[0]
                    coin = sym[:-4] if sym.endswith("USDT") else sym
                    interval_map[coin] = row[1]
        except Exception as exc:
            logger.error("Failed to query funding caps: %s", exc)

        # Get realtime basis: first from data_fetcher cache (arbitrage API)
        from app.services.data_fetcher import data_fetcher
        cached = data_fetcher.get_cached_data()
        basis_map: Dict[str, float] = {}
        for pair_key, pair_data in cached.items():
            if not isinstance(pair_data, dict):
                continue
            for item in pair_data.get("data", []):
                coin_name = item.get("coinName", "")
                short_premium = item.get("shortPremium")
                if coin_name and short_premium is not None:
                    premium_pct = float(short_premium) * 100
                    if coin_name not in basis_map or premium_pct < basis_map[coin_name]:
                        basis_map[coin_name] = round(premium_pct, 4)

        # Fill missing basis from Binance premiumIndex (for coins only on Binance)
        missing_coins = [c["coin_name"] for c in coins if c["coin_name"] not in basis_map]
        if missing_coins:
            bn_premium = await _get_binance_premium()
            for coin in missing_coins:
                if coin in bn_premium:
                    basis_map[coin] = bn_premium[coin]

        # Attach all data
        for c in coins:
            c["cumulative_funding"] = funding_map.get(c["coin_name"])
            c["realtime_basis"] = basis_map.get(c["coin_name"])
            c["settlement_period"] = interval_map.get(c["coin_name"])

        return {"data": coins}
    except Exception as exc:
        logger.error("Failed to fetch premium filter: %s", exc)
        return {"data": [], "error": str(exc)}


@router.get("/basis")
async def get_realtime_basis(coins: str = Query(..., description="Comma-separated coin names")):
    """Get realtime basis for specific coins. Used by frontend for 5s polling.

    First checks data_fetcher cache, then falls back to Binance premiumIndex.
    """
    coin_list = [c.strip() for c in coins.split(",") if c.strip()]
    if not coin_list:
        return {"data": {}}

    # From data_fetcher cache
    from app.services.data_fetcher import data_fetcher
    cached = data_fetcher.get_cached_data()
    basis_map: Dict[str, float] = {}
    for pair_key, pair_data in cached.items():
        if not isinstance(pair_data, dict):
            continue
        for item in pair_data.get("data", []):
            coin_name = item.get("coinName", "")
            if coin_name not in coin_list:
                continue
            short_premium = item.get("shortPremium")
            if short_premium is not None:
                premium_pct = float(short_premium) * 100
                if coin_name not in basis_map or premium_pct < basis_map[coin_name]:
                    basis_map[coin_name] = round(premium_pct, 4)

    # Fill missing from Binance premiumIndex
    missing = [c for c in coin_list if c not in basis_map]
    if missing:
        bn_premium = await _get_binance_premium()
        for coin in missing:
            if coin in bn_premium:
                basis_map[coin] = bn_premium[coin]

    return {"data": basis_map}
