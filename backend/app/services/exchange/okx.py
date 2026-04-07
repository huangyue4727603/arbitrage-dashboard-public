import logging
from typing import Any, Optional

import aiohttp

from app.config import get_proxy

logger = logging.getLogger(__name__)


class OKXClient:
    """Async client for the OKX public API."""

    BASE_URL = "https://www.okx.com"

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

    async def __aenter__(self) -> "OKXClient":
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
        """Execute an HTTP request against the OKX API.

        OKX wraps all responses in ``{"code": "0", "data": [...]}``.  This
        helper extracts the ``data`` field on success and returns ``None``
        on any error.
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
                if body.get("code") != "0":
                    logger.error(
                        "OKX API error on %s: code=%s msg=%s",
                        path,
                        body.get("code"),
                        body.get("msg"),
                    )
                    return None
                return body.get("data")
        except Exception as exc:
            logger.error("OKX request %s %s failed: %s", method, path, exc)
            return None

    # ------------------------------------------------------------------
    # Public API methods
    # ------------------------------------------------------------------

    async def get_funding_rate_history(
        self,
        inst_id: str,
        before: Optional[str] = None,
        after: Optional[str] = None,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """GET /api/v5/public/funding-rate-history

        inst_id format: BTC-USDT-SWAP
        """
        params: dict[str, Any] = {"instId": inst_id, "limit": str(limit)}
        if before is not None:
            params["before"] = before
        if after is not None:
            params["after"] = after
        result = await self._request(
            "GET", "/api/v5/public/funding-rate-history", params=params, timeout=timeout
        )
        return result if isinstance(result, list) else []

    async def get_funding_rate(
        self,
        inst_id: str,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        """GET /api/v5/public/funding-rate - Current funding rate including caps.

        Returns fields: fundingRate, nextFundingRate, fundingTime,
        maxFundingRate, minFundingRate.
        """
        params: dict[str, Any] = {"instId": inst_id}
        result = await self._request(
            "GET", "/api/v5/public/funding-rate", params=params, timeout=timeout
        )
        if isinstance(result, list) and len(result) > 0:
            return result[0]
        return {}

    async def get_candles(
        self,
        inst_id: str,
        bar: str = "1H",
        before: Optional[str] = None,
        after: Optional[str] = None,
        limit: int = 100,
        timeout: Optional[int] = None,
    ) -> list[list[str]]:
        """GET /api/v5/market/candles

        bar: 1m, 5m, 15m, 1H, 4H, 1D, etc.
        """
        params: dict[str, Any] = {
            "instId": inst_id,
            "bar": bar,
            "limit": str(limit),
        }
        if before is not None:
            params["before"] = before
        if after is not None:
            params["after"] = after
        result = await self._request(
            "GET", "/api/v5/market/candles", params=params, timeout=timeout
        )
        return result if isinstance(result, list) else []

    async def get_ticker(
        self,
        inst_id: str,
        timeout: Optional[int] = None,
    ) -> dict[str, Any]:
        """GET /api/v5/market/ticker"""
        params: dict[str, Any] = {"instId": inst_id}
        result = await self._request(
            "GET", "/api/v5/market/ticker", params=params, timeout=timeout
        )
        if isinstance(result, list) and len(result) > 0:
            return result[0]
        return {}

    async def get_tickers(
        self,
        inst_type: str = "SWAP",
        timeout: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """GET /api/v5/market/tickers - All tickers for instrument type."""
        params: dict[str, Any] = {"instType": inst_type}
        result = await self._request(
            "GET", "/api/v5/market/tickers", params=params, timeout=timeout
        )
        return result if isinstance(result, list) else []


    async def get_index_components(self, index: str, timeout: Optional[int] = None) -> dict[str, Any]:
        """GET /api/v5/market/index-components?index=BTC-USDT — spot index constituents."""
        result = await self._request(
            "GET", "/api/v5/market/index-components", params={"index": index}, timeout=timeout
        )
        if isinstance(result, list) and result:
            return result[0]
        if isinstance(result, dict):
            return result
        return {}


# Module-level singleton instance
okx_client = OKXClient()
