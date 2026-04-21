from datetime import datetime
from typing import Optional, Dict, List, Tuple, Any
import logging

import aiohttp

from app.config import get_proxy

from app.services.data_fetcher import data_fetcher

logger = logging.getLogger(__name__)


class UnhedgedService:
    """Detect unhedged arbitrage opportunities."""

    def __init__(self) -> None:
        # Cooldown tracking: {(coin, long_ex, short_ex, type): last_alert_time}
        self._cooldowns: Dict[Tuple[str, str, str, str], datetime] = {}
        self._alerts: List[dict] = []

    async def process_data(self, api_data: Dict[str, Any]) -> List[dict]:
        """
        Process data from self-hosted API to find unhedged opportunities.

        api_data is the merged dict from data_fetcher.fetch_all_data(), keyed by
        pair identifier (e.g. "BYBIT_BINANCE", "OKX_BINANCE").

        For each item in data:
        - Long exchange (A): basis a1 (longPremium), funding rate a2 (longFundingRate), price a3 (bid)
        - Short exchange (B): basis b1 (shortPremium), funding rate b2 (shortFundingRate), price b3 (ask)

        Funding rate sign handling (CRITICAL):
        - actual_long_funding = -a2
        - actual_short_funding = b2
        - Funding diff c = -a2 - b2

        Spread d = (b3 - a3) / a3

        Type 1 (资费差套利): a1 < a2 AND c + d > 0 AND b1 < -1
        Type 2 (资费打开价差没打开): d < -0.005 AND b1 < -3
        """
        type1_alerts: List[dict] = []
        type2_alerts: List[dict] = []

        for pair_key, pair_data in api_data.items():
            if not pair_data or not isinstance(pair_data, dict):
                continue

            items = pair_data.get("data", pair_data)
            if isinstance(items, dict):
                items = items.get("data", [])
            if not isinstance(items, list):
                continue

            for item in items:
                try:
                    coin = item.get("symbolName", item.get("coin", ""))
                    if not coin:
                        continue

                    a1 = float(item.get("longPremium", 0))
                    a2 = float(item.get("longFundingRate", 0))
                    a3 = float(item.get("bid", 0))
                    b1 = float(item.get("shortPremium", 0))
                    b2 = float(item.get("shortFundingRate", 0))
                    b3 = float(item.get("ask", 0))

                    long_exchange = item.get("longExchange", pair_key.split("_")[0])
                    short_exchange = item.get("shortExchange", pair_key.split("_")[1] if "_" in pair_key else "BINANCE")

                    if a3 <= 0:
                        continue

                    # Funding diff: actual_long_funding - actual_short_funding = -a2 - b2
                    funding_diff = -a2 - b2
                    # Spread
                    spread = (b3 - a3) / a3

                    now = datetime.now()

                    # Type 1: 资费差套利
                    if a1 < a2 and (funding_diff + spread) > 0 and b1 < -1:
                        if self._check_cooldown(coin, long_exchange, short_exchange, "type1"):
                            alert = {
                                "type": "type1",
                                "coin": coin,
                                "long_exchange": long_exchange,
                                "short_exchange": short_exchange,
                                "spread": round(spread * 100, 4),
                                "funding_diff": round(funding_diff * 100, 4),
                                "short_basis": round(b1, 4),
                                "alert_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                                "timestamp": now.timestamp(),
                            }
                            type1_alerts.append(alert)
                            self._set_cooldown(coin, long_exchange, short_exchange, "type1")

                    # Type 2: 资费打开价差没打开
                    if spread < -0.005 and b1 < -3:
                        if self._check_cooldown(coin, long_exchange, short_exchange, "type2"):
                            price_change_5m = await self._fetch_price_change_5m(coin)
                            alert = {
                                "type": "type2",
                                "coin": coin,
                                "short_exchange": short_exchange,
                                "long_exchange": long_exchange,
                                "spread": round(spread * 100, 4),
                                "short_basis": round(b1, 4),
                                "price_change_5m": round(price_change_5m * 100, 4),
                                "alert_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                                "timestamp": now.timestamp(),
                            }
                            type2_alerts.append(alert)
                            self._set_cooldown(coin, long_exchange, short_exchange, "type2")

                except Exception as exc:
                    logger.debug("Error processing item %s: %s", item, exc)
                    continue

        all_alerts = type1_alerts + type2_alerts

        # Keep recent alerts (last 100), newest first
        if all_alerts:
            self._alerts = (all_alerts + self._alerts)[:100]

        return all_alerts

    def _check_cooldown(self, coin: str, long_ex: str, short_ex: str, alert_type: str) -> bool:
        """Check if alert is allowed (not in cooldown). Returns True if allowed."""
        key = (coin, long_ex, short_ex, alert_type)
        last = self._cooldowns.get(key)
        if last and (datetime.now() - last).total_seconds() < 3600:
            return False
        return True

    def _set_cooldown(self, coin: str, long_ex: str, short_ex: str, alert_type: str) -> None:
        """Set cooldown for this alert combination."""
        key = (coin, long_ex, short_ex, alert_type)
        self._cooldowns[key] = datetime.now()

    def get_alerts(self) -> List[dict]:
        """Get current unhedged opportunity alerts."""
        return self._alerts

    async def _fetch_price_change_5m(self, coin: str) -> float:
        """Fetch 5-minute price change from Binance kline API."""
        from app.services.exchange.binance import _cooldown_until
        import time as _time
        if _time.time() < _cooldown_until:
            return 0.0
        symbol = coin.upper() + "USDT"
        url = "https://fapi.binance.com/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": "5m",
            "limit": 2,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=5), proxy=get_proxy() or None) as resp:
                    if resp.status != 200:
                        return 0.0
                    data = await resp.json()
                    if not data or len(data) < 2:
                        return 0.0
                    # Each kline: [open_time, open, high, low, close, ...]
                    prev_close = float(data[-2][4])
                    curr_close = float(data[-1][4])
                    if prev_close <= 0:
                        return 0.0
                    return (curr_close - prev_close) / prev_close
        except Exception as exc:
            logger.debug("Failed to fetch Binance 5m kline for %s: %s", symbol, exc)
            return 0.0


# Module-level singleton
unhedged_service = UnhedgedService()
