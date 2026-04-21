import logging
import time
from typing import Any, Optional, Union

import aiohttp

from app.config import get_proxy

logger = logging.getLogger(__name__)

# Per-path cooldown: different endpoints get independent cooldowns
# so that e.g. /constituents getting 418 doesn't block /fundingRate
_cooldown_map: dict[str, float] = {}  # path -> cooldown_until timestamp
_COOLDOWN_SECONDS = 300  # 5 minutes default cooldown after 418


def _get_cooldown_group(path: str) -> str:
    """Map an API path to its cooldown group.

    Endpoints in the same group share a cooldown timer.
    Critical data endpoints are isolated from non-critical ones.
    """
    if "/fundingRate" in path:
        return "funding"
    if "/klines" in path:
        return "klines"
    if "/fundingInfo" in path:
        return "fundingInfo"
    if "/exchangeInfo" in path:
        return "exchangeInfo"
    if "/constituents" in path:
        return "constituents"
    if "/ticker" in path or "/premiumIndex" in path:
        return "ticker"
    if "/openInterest" in path:
        return "oi"
    return "other"


class BinanceClient:
    """Async client for the Binance Futures (FAPI) public API."""

    BASE_URL = "https://fapi.binance.com"

    def __init__(self, base_url: Optional[str] = None, timeout: int = 15):
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "BinanceClient":
        await self._get_session()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        params: Optional[dict[str, Any]] = None,
        timeout: Optional[int] = None,
    ) -> Any:
        """Execute an HTTP request and return the parsed JSON response.

        Returns an empty list or dict (matching the expected return type of
        the caller) on any network / HTTP error so that upstream code does
        not need to handle exceptions from the exchange layer.

        Uses per-endpoint-group cooldowns so that e.g. /constituents getting
        418 does NOT block /fundingRate requests.
        """
        group = _get_cooldown_group(path)

        # Check per-group cooldown
        now = time.time()
        cooldown_until = _cooldown_map.get(group, 0.0)
        if now < cooldown_until:
            remaining = int(cooldown_until - now)
            logger.debug("Binance [%s] cooldown active (%ds remaining), skipping %s %s",
                         group, remaining, method, path)
            return None

        session = await self._get_session()
        url = f"{self.base_url}{path}"
        req_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else None
        proxy = get_proxy() or None
        try:
            async with session.request(
                method, url, params=params, timeout=req_timeout, proxy=proxy
            ) as resp:
                if resp.status in (418, 429):
                    # Try to parse ban expiry from Binance response
                    try:
                        body = await resp.json()
                        msg = body.get("msg", "")
                        # Parse "banned until <timestamp_ms>"
                        if "banned until" in msg:
                            ban_ts = int(msg.split("banned until")[1].split(".")[0].strip())
                            _cooldown_map[group] = ban_ts / 1000
                            wait_sec = int(_cooldown_map[group] - time.time())
                            logger.warning(
                                "Binance [%s] %s %s: IP banned until %s (%d seconds)",
                                group, method, path,
                                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(_cooldown_map[group])),
                                max(wait_sec, 0),
                            )
                        else:
                            _cooldown_map[group] = time.time() + _COOLDOWN_SECONDS
                            logger.warning(
                                "Binance [%s] %s %s: status %d, cooldown %ds",
                                group, method, path, resp.status, _COOLDOWN_SECONDS
                            )
                    except Exception:
                        _cooldown_map[group] = time.time() + _COOLDOWN_SECONDS
                        logger.warning(
                            "Binance [%s] %s %s: status %d, cooldown %ds",
                            group, method, path, resp.status, _COOLDOWN_SECONDS
                        )
                    raise aiohttp.ClientResponseError(
                        resp.request_info, resp.history,
                        status=resp.status, message=f"Rate limited ({resp.status})"
                    )
                resp.raise_for_status()
                return await resp.json()
        except aiohttp.ClientResponseError as exc:
            if exc.status in (418, 429):
                raise  # Let caller handle rate limits
            logger.error("Binance request %s %s failed: %s", method, path, exc)
            return None
        except Exception as exc:
            logger.error("Binance request %s %s failed: %s", method, path, exc)
            return None

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_funding_rate_history(
        self,
        symbol: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000,
        timeout: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """GET /fapi/v1/fundingRate - Historical funding rates."""
        params: dict[str, Any] = {"symbol": symbol, "limit": limit}
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        result = await self._request("GET", "/fapi/v1/fundingRate", params=params, timeout=timeout)
        return result if isinstance(result, list) else []

    async def get_funding_info(self, timeout: Optional[int] = None) -> list[dict[str, Any]]:
        """GET /fapi/v1/fundingInfo - Funding rate caps/floors and settlement intervals for all symbols."""
        result = await self._request("GET", "/fapi/v1/fundingInfo", timeout=timeout)
        return result if isinstance(result, list) else []

    async def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 500,
        timeout: Optional[int] = None,
    ) -> list[list[Any]]:
        """GET /fapi/v1/klines - K-line/candlestick data.

        interval: 1m, 5m, 15m, 1h, 4h, 1d, etc.
        Returns: [[open_time, open, high, low, close, volume, close_time, ...], ...]
        """
        params: dict[str, Any] = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        result = await self._request("GET", "/fapi/v1/klines", params=params, timeout=timeout)
        return result if isinstance(result, list) else []

    async def get_ticker_price(
        self,
        symbol: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Union[list[dict[str, Any]], dict[str, Any]]:
        """GET /fapi/v2/ticker/price - Latest price for symbol or all symbols."""
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = symbol
        result = await self._request("GET", "/fapi/v2/ticker/price", params=params, timeout=timeout)
        if result is None:
            return {} if symbol else []
        return result

    async def get_open_interest(
        self,
        symbol: str,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        """GET /fapi/v1/openInterest - Current open interest."""
        params: dict[str, Any] = {"symbol": symbol}
        result = await self._request("GET", "/fapi/v1/openInterest", params=params, timeout=timeout)
        return result if isinstance(result, dict) else {}

    async def get_exchange_info(self, timeout: Optional[int] = None) -> dict[str, Any]:
        """GET /fapi/v1/exchangeInfo - All trading pair info."""
        result = await self._request("GET", "/fapi/v1/exchangeInfo", timeout=timeout)
        return result if isinstance(result, dict) else {}

    async def get_premium_index(self, timeout: Optional[int] = None) -> list[dict[str, Any]]:
        """GET /fapi/v1/premiumIndex - All symbols' funding rate and mark price."""
        result = await self._request("GET", "/fapi/v1/premiumIndex", timeout=timeout)
        return result if isinstance(result, list) else []

    async def get_all_tickers(self, timeout: Optional[int] = None) -> list[dict[str, Any]]:
        """GET /fapi/v2/ticker/price - All prices at once."""
        result = await self._request("GET", "/fapi/v2/ticker/price", timeout=timeout)
        return result if isinstance(result, list) else []

    async def get_index_constituents(self, symbol: str, timeout: Optional[int] = None) -> dict[str, Any]:
        """GET /fapi/v1/constituents?symbol=BTCUSDT — index price spot constituents."""
        result = await self._request("GET", "/fapi/v1/constituents", params={"symbol": symbol}, timeout=timeout)
        return result if isinstance(result, dict) else {}

    async def get_24hr_ticker(
        self,
        symbol: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> Union[list[dict[str, Any]], dict[str, Any]]:
        """GET /fapi/v1/ticker/24hr - 24hr price change statistics."""
        params: dict[str, Any] = {}
        if symbol is not None:
            params["symbol"] = symbol
        result = await self._request("GET", "/fapi/v1/ticker/24hr", params=params, timeout=timeout)
        if result is None:
            return {} if symbol else []
        return result


# Module-level singleton instance
binance_client = BinanceClient()
