import asyncio
import logging
import time
import math
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.config import get_settings
from app.database import async_session_factory
from app.models.market_data import FundingCap
from app.services.exchange.binance import BinanceClient
from app.services.exchange.okx import OKXClient
from app.services.exchange.bybit import BybitClient

logger = logging.getLogger(__name__)
settings = get_settings()

# Self-hosted API URL
SELF_API_URL = settings.ARBITRAGE_API_URL.rstrip("/")

# Exchange display names
EXCHANGE_BINANCE = "Binance"
EXCHANGE_OKX = "OKX"
EXCHANGE_BYBIT = "Bybit"

# Allowed settlement intervals (exclude 1h)
ALLOWED_INTERVALS_HOURS = {8, 4, 2}


def _coin_from_bn_symbol(symbol: str) -> Optional[str]:
    if symbol.endswith("USDT"):
        return symbol[:-4]
    return None


def _coin_from_bybit_symbol(symbol: str) -> Optional[str]:
    if symbol.endswith("USDT"):
        return symbol[:-4]
    return None


def _coin_from_okx_inst_id(inst_id: str) -> Optional[str]:
    parts = inst_id.split("-")
    if len(parts) >= 3 and parts[1] == "USDT" and parts[2] == "SWAP":
        return parts[0]
    return None


def _calculate_countdown_seconds(interval_hours: int, exchange: str) -> int:
    """Calculate seconds until next funding settlement.

    All three exchanges settle at fixed intervals aligned to 00:00 UTC.
    - 8h: settles at 00:00, 08:00, 16:00 UTC
    - 4h: settles at 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
    - 2h: settles at every even hour UTC
    """
    now = time.time()
    interval_seconds = interval_hours * 3600

    # Current time within the day (seconds since midnight UTC)
    utc_midnight = now - (now % 86400)
    seconds_since_midnight = now - utc_midnight

    # Find the next settlement time
    # Settlement times are at 0, interval_seconds, 2*interval_seconds, etc. from midnight
    current_slot = math.floor(seconds_since_midnight / interval_seconds)
    next_settlement_since_midnight = (current_slot + 1) * interval_seconds

    if next_settlement_since_midnight >= 86400:
        # Next settlement is tomorrow at 00:00
        countdown = int(86400 - seconds_since_midnight)
    else:
        countdown = int(next_settlement_since_midnight - seconds_since_midnight)

    return max(countdown, 0)


async def _upsert_funding_caps(exchange: str, caps_data: Dict[str, Dict[str, Any]]) -> None:
    """Upsert funding caps into DB."""
    if not caps_data:
        return
    async with async_session_factory() as db:
        try:
            for symbol, info in caps_data.items():
                stmt = mysql_insert(FundingCap).values(
                    exchange=exchange,
                    symbol=symbol,
                    funding_cap=info.get("cap", 0),
                    funding_floor=info.get("floor", 0),
                    interval_hours=info.get("interval_hours", 8),
                )
                stmt = stmt.on_duplicate_key_update(
                    funding_cap=stmt.inserted.funding_cap,
                    funding_floor=stmt.inserted.funding_floor,
                    interval_hours=stmt.inserted.interval_hours,
                )
                await db.execute(stmt)
            await db.commit()
            logger.info("Upserted %d funding caps for %s", len(caps_data), exchange)
        except Exception as exc:
            logger.error("Failed to upsert funding caps for %s: %s", exchange, exc)
            await db.rollback()


class FundingBreakService:
    """Detect coins where funding rate is about to break settlement cycle threshold."""

    def __init__(self) -> None:
        self._caps_last_refresh: float = 0.0
        self._caps_ttl: float = 3600.0  # 1 hour
        self._alert_history: List[Dict[str, Any]] = []
        self._alerted_keys: set = set()

    async def _fetch_self_api_data(self) -> List[Dict[str, Any]]:
        """Get real-time data from the shared data_fetcher cache.

        Reuses data already fetched by realtime_scheduler every 3s,
        avoiding duplicate API calls and timeout issues.
        """
        from app.services.data_fetcher import data_fetcher

        cached = data_fetcher.get_cached_data()
        if not cached:
            logger.warning("No cached data from data_fetcher for funding break")
            return []

        # Flatten all exchange pair data into a single list
        all_items: List[Dict[str, Any]] = []
        for pair_key, pair_data in cached.items():
            items = pair_data.get("data", []) if isinstance(pair_data, dict) else []
            all_items.extend(items)

        return all_items

    async def _refresh_binance_caps(self) -> None:
        """Fetch Binance funding caps/floors and intervals, save to DB."""
        try:
            async with BinanceClient() as client:
                info_list = await client.get_funding_info()
                caps: Dict[str, Dict[str, Any]] = {}
                for item in info_list:
                    symbol = item.get("symbol", "")
                    coin = _coin_from_bn_symbol(symbol)
                    if not coin:
                        continue
                    interval_hours = item.get("fundingIntervalHours", 8)
                    cap = float(item.get("adjustedFundingRateCap", "0.03"))
                    floor = float(item.get("adjustedFundingRateFloor", "-0.03"))
                    caps[coin] = {
                        "cap": cap,
                        "floor": floor,
                        "interval_hours": interval_hours,
                    }
                await _upsert_funding_caps("Binance", caps)
                logger.info("Binance funding caps refreshed: %d symbols", len(caps))
        except Exception as exc:
            logger.error("Failed to refresh Binance caps: %s", exc)

    async def _refresh_okx_caps(self) -> None:
        """Fetch OKX funding caps and save to DB."""
        try:
            async with OKXClient() as client:
                tickers = await client.get_tickers(inst_type="SWAP")
                okx_inst_ids = []
                for t in tickers:
                    inst_id = t.get("instId", "")
                    if "-USDT-SWAP" in inst_id:
                        okx_inst_ids.append(inst_id)

                caps: Dict[str, Dict[str, Any]] = {}
                batch_size = 20
                for i in range(0, len(okx_inst_ids), batch_size):
                    batch = okx_inst_ids[i:i + batch_size]
                    tasks = [client.get_funding_rate(inst_id) for inst_id in batch]
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    for inst_id, result in zip(batch, results):
                        if isinstance(result, Exception) or not result:
                            continue
                        coin = _coin_from_okx_inst_id(inst_id)
                        if not coin:
                            continue
                        max_rate = float(result.get("maxFundingRate", "0.015"))
                        min_rate = float(result.get("minFundingRate", "-0.015"))
                        # Calculate interval from fundingTime and nextFundingTime
                        interval_hours = 8
                        try:
                            ft = int(result.get("fundingTime", 0))
                            nft = int(result.get("nextFundingTime", 0))
                            if ft > 0 and nft > 0 and nft > ft:
                                interval_hours = max(1, (nft - ft) // 3600000)
                        except (ValueError, TypeError):
                            pass
                        caps[coin] = {
                            "cap": max_rate,
                            "floor": min_rate,
                            "interval_hours": interval_hours,
                        }
                    if i + batch_size < len(okx_inst_ids):
                        await asyncio.sleep(0.2)

                await _upsert_funding_caps("OKX", caps)
                logger.info("OKX funding caps refreshed: %d symbols", len(caps))
        except Exception as exc:
            logger.error("Failed to refresh OKX caps: %s", exc)

    async def _refresh_bybit_caps(self) -> None:
        """Fetch Bybit funding caps/floors and save to DB."""
        try:
            async with BybitClient() as client:
                instruments = await client.get_instruments_info()
                caps: Dict[str, Dict[str, Any]] = {}
                for inst in instruments:
                    if inst.get("status") != "Trading":
                        continue
                    if inst.get("quoteCoin") != "USDT":
                        continue
                    symbol = inst.get("symbol", "")
                    coin = _coin_from_bybit_symbol(symbol)
                    if not coin:
                        continue
                    interval_minutes = int(inst.get("fundingInterval", 480))
                    interval_hours = interval_minutes // 60
                    upper = float(inst.get("upperFundingRate", "0.01"))
                    lower = float(inst.get("lowerFundingRate", "-0.01"))
                    caps[coin] = {
                        "cap": upper,
                        "floor": lower,
                        "interval_hours": interval_hours,
                    }
                await _upsert_funding_caps("Bybit", caps)
                logger.info("Bybit funding caps refreshed: %d symbols", len(caps))
        except Exception as exc:
            logger.error("Failed to refresh Bybit caps: %s", exc)

    async def refresh_caps(self) -> None:
        """Refresh all exchange caps if stale."""
        now = time.time()
        if now - self._caps_last_refresh < self._caps_ttl:
            return
        logger.info("Refreshing funding caps from all exchanges...")
        await asyncio.gather(
            self._refresh_binance_caps(),
            self._refresh_okx_caps(),
            self._refresh_bybit_caps(),
        )
        self._caps_last_refresh = now

    async def force_refresh_caps(self) -> None:
        """Force refresh caps regardless of TTL."""
        self._caps_last_refresh = 0.0
        await self.refresh_caps()

    async def _load_caps_from_db(self) -> Dict[str, Dict[str, Dict[str, Any]]]:
        """Load all funding caps from DB, grouped by exchange."""
        result_map: Dict[str, Dict[str, Dict[str, Any]]] = {
            "BINANCE": {},
            "OKX": {},
            "BYBIT": {},
        }
        async with async_session_factory() as db:
            result = await db.execute(select(FundingCap))
            rows = result.scalars().all()
            for row in rows:
                ex_key = row.exchange.upper()
                if ex_key not in result_map:
                    result_map[ex_key] = {}
                result_map[ex_key][row.symbol] = {
                    "cap": row.funding_cap,
                    "floor": row.funding_floor,
                    "interval_hours": row.interval_hours,
                }
        return result_map

    def _build_breaking_items_from_api_data(
        self, api_data: List[Dict[str, Any]], caps_db: Dict[str, Dict[str, Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        """Process self-hosted API data and find coins breaking their funding cap."""
        seen: Dict[Tuple[str, str], Dict[str, Any]] = {}

        for item in api_data:
            coin = item.get("coinName", "")
            if not coin:
                continue

            long_exchange = item.get("longExchange", "")
            long_inst_type = item.get("arbitrageSymbol", {}).get("l", {}).get("instType", "")
            if long_inst_type == "PERP" and long_exchange in ("BINANCE", "OKX", "BYBIT"):
                key = (long_exchange, coin)
                if key not in seen:
                    seen[key] = {
                        "exchange": long_exchange,
                        "coin": coin,
                        "realtime_funding": item.get("originLongFundingRate", 0),
                        "funding_rate_8h": item.get("longFundingRate", 0),
                        "interval_hours": item.get("longFundingInterval", 8),
                        "premium": item.get("longPremium", 0),
                    }

            short_exchange = item.get("shortExchange", "")
            short_inst_type = item.get("arbitrageSymbol", {}).get("s", {}).get("instType", "")
            if short_inst_type == "PERP" and short_exchange in ("BINANCE", "OKX", "BYBIT"):
                key = (short_exchange, coin)
                if key not in seen:
                    seen[key] = {
                        "exchange": short_exchange,
                        "coin": coin,
                        "realtime_funding": item.get("originShortFundingRate", 0),
                        "funding_rate_8h": item.get("shortFundingRate", 0),
                        "interval_hours": item.get("shortFundingInterval", 8),
                        "premium": item.get("shortPremium", 0),
                    }

        results: List[Dict[str, Any]] = []

        for (exchange, coin), data in seen.items():
            interval_hours = data.get("interval_hours", 8)

            if interval_hours not in ALLOWED_INTERVALS_HOURS:
                continue

            realtime_funding = data.get("realtime_funding", 0)
            if realtime_funding is None:
                realtime_funding = 0

            premium = data.get("premium", 0)
            if premium is None:
                premium = 0

            # Get cap/floor from DB data
            info = caps_db.get(exchange, {}).get(coin, {})
            cap = info.get("cap")
            floor = info.get("floor")

            if info.get("interval_hours"):
                interval_hours = info["interval_hours"]

            if interval_hours not in ALLOWED_INTERVALS_HOURS:
                continue

            if cap is None or floor is None:
                continue

            is_breaking = (realtime_funding >= cap) or (realtime_funding <= floor)

            exchange_display = {
                "BINANCE": EXCHANGE_BINANCE,
                "OKX": EXCHANGE_OKX,
                "BYBIT": EXCHANGE_BYBIT,
            }.get(exchange, exchange)

            interval_label = f"{interval_hours}h"
            countdown = _calculate_countdown_seconds(interval_hours, exchange)

            results.append({
                "coin_name": coin,
                "exchange": exchange_display,
                "funding_cap": round(cap * 100, 4),
                "funding_floor": round(floor * 100, 4),
                "realtime_funding": round(realtime_funding * 100, 4),
                "current_interval": interval_label,
                "basis": round(premium * 100, 4),
                "countdown_seconds": countdown,
                "is_breaking": is_breaking,
            })

        results.sort(key=lambda x: x["countdown_seconds"])
        return results

    async def get_breaking_coins(self) -> List[Dict[str, Any]]:
        """Get all coins where funding rate is about to break settlement cycle threshold."""
        await self.refresh_caps()

        # Load caps from DB
        caps_db = await self._load_caps_from_db()

        # Fetch real-time data from self-hosted API
        api_data = await self._fetch_self_api_data()
        if not api_data:
            logger.warning("No data from self-hosted API for funding break detection")
            return []

        items = self._build_breaking_items_from_api_data(api_data, caps_db)

        # Detect new breaking coins for alerts
        self._detect_breaking_alerts(items)

        return items

    # ------------------------------------------------------------------
    # Breaking alerts (in-memory)
    # ------------------------------------------------------------------

    def _detect_breaking_alerts(self, items: List[Dict[str, Any]]) -> None:
        """Check for newly breaking coins and add to alert history."""
        from datetime import datetime
        now = datetime.now()

        for item in items:
            if not item.get("is_breaking"):
                continue

            key = f"{item['coin_name']}_{item['exchange']}"
            if key in self._alerted_keys:
                continue

            self._alerted_keys.add(key)
            self._alert_history.insert(0, {
                "coin_name": item["coin_name"],
                "exchange": item["exchange"],
                "realtime_funding": item["realtime_funding"],
                "funding_cap": item["funding_cap"],
                "basis": item["basis"],
                "alert_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "timestamp": now.timestamp(),
            })
            logger.info("Funding break alert: %s on %s (rate=%s, cap=%s)",
                        item["coin_name"], item["exchange"],
                        item["realtime_funding"], item["funding_cap"])

        # Keep under 500
        if len(self._alert_history) > 500:
            self._alert_history = self._alert_history[:500]

    def get_alert_history(self) -> List[Dict[str, Any]]:
        """Return funding break alert history."""
        return self._alert_history

    def clear_alerts(self) -> None:
        """Clear alert history and alerted keys."""
        self._alert_history = []
        self._alerted_keys = set()
        logger.info("Funding break alerts cleared")


# Module-level singleton
funding_break_service = FundingBreakService()
