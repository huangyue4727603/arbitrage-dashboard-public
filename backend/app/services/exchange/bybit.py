import logging
from typing import Any, Optional

import aiohttp

from app.config import get_proxy

logger = logging.getLogger(__name__)


class BybitClient:
    """Async client for the Bybit V5 public API."""

    BASE_URL = "https://api.bybit.com"

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

    async def __aenter__(self) -> "BybitClient":
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
        """Execute an HTTP request against the Bybit API.

        Bybit V5 wraps responses in ``{"retCode": 0, "result": {...}}``.
        This helper extracts the ``result`` field on success and returns
        ``None`` on any error.
        """
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        req_timeout = aiohttp.ClientTimeout(total=timeout) if timeout else None
        proxy = get_proxy() or None
        try:
            async with session.request(
                method, url, params=params, timeout=req_timeout, proxy=proxy
            ) as resp:
                resp.raise_for_status()
                body = await resp.json()
                ret_code = body.get("retCode")
                if ret_code != 0:
                    logger.error(
                        "Bybit API error on %s: retCode=%s retMsg=%s",
                        path,
                        ret_code,
                        body.get("retMsg"),
                    )
                    return None
                return body.get("result")
        except Exception as exc:
            logger.error("Bybit request %s %s failed: %s", method, path, exc)
            return None

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_funding_rate_history(
        self,
        symbol: str,
        category: str = "linear",
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 200,
        timeout: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """GET /v5/market/funding/history"""
        params: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "limit": limit,
        }
        if start_time is not None:
            params["startTime"] = start_time
        if end_time is not None:
            params["endTime"] = end_time
        result = await self._request(
            "GET", "/v5/market/funding/history", params=params, timeout=timeout
        )
        if isinstance(result, dict):
            return result.get("list", [])
        return []

    async def get_tickers(
        self,
        category: str = "linear",
        symbol: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """GET /v5/market/tickers - Real-time price, funding rate info."""
        params: dict[str, Any] = {"category": category}
        if symbol is not None:
            params["symbol"] = symbol
        result = await self._request(
            "GET", "/v5/market/tickers", params=params, timeout=timeout
        )
        if isinstance(result, dict):
            return result.get("list", [])
        return []

    async def get_kline(
        self,
        symbol: str,
        interval: str,
        category: str = "linear",
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = 200,
        timeout: Optional[int] = None,
    ) -> list[list[str]]:
        """GET /v5/market/kline

        interval: 1, 3, 5, 15, 30, 60, 120, 240, 360, 720, D, W, M
        """
        params: dict[str, Any] = {
            "category": category,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        }
        if start is not None:
            params["start"] = start
        if end is not None:
            params["end"] = end
        result = await self._request(
            "GET", "/v5/market/kline", params=params, timeout=timeout
        )
        if isinstance(result, dict):
            return result.get("list", [])
        return []

    async def get_instruments_info(
        self,
        category: str = "linear",
        symbol: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """GET /v5/market/instruments-info - Trading pair info."""
        params: dict[str, Any] = {"category": category}
        if symbol is not None:
            params["symbol"] = symbol
        result = await self._request(
            "GET", "/v5/market/instruments-info", params=params, timeout=timeout
        )
        if isinstance(result, dict):
            return result.get("list", [])
        return []


# Module-level singleton instance
bybit_client = BybitClient()
