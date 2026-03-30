import asyncio
import logging
from typing import Any, Optional

import aiohttp

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class DataFetcher:
    """Unified data fetcher for the self-hosted arbitrage API.

    Implements the singleton pattern -- use ``DataFetcher.instance()`` or the
    module-level ``data_fetcher`` variable to get the shared instance.
    """

    _instance: Optional["DataFetcher"] = None

    def __new__(cls, *args: Any, **kwargs: Any) -> "DataFetcher":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, base_url: Optional[str] = None):
        # Guard against re-initialisation on repeated __new__ returns.
        if getattr(self, "_initialised", False):
            return
        self.base_url = (base_url or settings.ARBITRAGE_API_URL).rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self._last_data: dict[str, Any] = {}
        self._on_pair_complete: Optional[Any] = None  # async callback(data)
        self._initialised = True

    @classmethod
    def instance(cls, base_url: Optional[str] = None) -> "DataFetcher":
        """Return the singleton instance, creating it if necessary."""
        return cls(base_url=base_url)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30, sock_read=20)
            self._session = aiohttp.ClientSession(timeout=timeout, trust_env=False)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> "DataFetcher":
        await self._get_session()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # API methods
    # ------------------------------------------------------------------

    async def fetch_arbitrage_data(
        self,
        long_exchanges: list[str],
        short_exchanges: list[str],
        all_data: bool = True,
    ) -> dict[str, Any]:
        """Fetch arbitrage data from the self-hosted API.

        Args:
            long_exchanges: List of exchange names for long positions.
            short_exchanges: List of exchange names for short positions.
            all_data: When True, request all available data from the API.

        Returns:
            Dict containing the API response data. Returns an empty dict on
            failure. Only returns perpetual-to-perpetual (LPerp_SPerp) data.
        """
        session = await self._get_session()
        payload: dict[str, Any] = {
            "acceptLongExchanges": long_exchanges,
            "acceptShortExchanges": short_exchanges,
        }
        if all_data:
            payload["allData"] = True

        try:
            async with session.post(
                f"{self.base_url}/api/v1/arbitrage/chance/list",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                # Filter to only perpetual-to-perpetual pairs to reduce data size
                if isinstance(data, dict) and "data" in data:
                    data["data"] = [
                        item for item in data["data"]
                        if item.get("chanceType") == "LPerp_SPerp"
                    ]
                return data
        except aiohttp.ClientError as exc:
            logger.error("Failed to fetch arbitrage data: %s", exc)
            return {}

    async def fetch_all_data(self) -> dict[str, Any]:
        """Fetch arbitrage data for all 6 exchange pairs and merge.

        Fetches in 2 batches of 3 to avoid overwhelming the proxy/API.
        Preserves previous cached data for any pair that fails.
        """
        pairs: list[tuple[list[str], list[str], str]] = [
            (["BYBIT"], ["BINANCE"], "BYBIT_BINANCE"),
            (["OKX"], ["BINANCE"], "OKX_BINANCE"),
            (["OKX"], ["BYBIT"], "OKX_BYBIT"),
            (["BINANCE"], ["OKX"], "BINANCE_OKX"),
            (["BINANCE"], ["BYBIT"], "BINANCE_BYBIT"),
            (["BYBIT"], ["OKX"], "BYBIT_OKX"),
        ]

        merged: dict[str, Any] = dict(self._last_data)  # preserve old data

        # Fetch pairs sequentially - update cache as each completes
        # Calls on_pair_complete callback after each pair for real-time alerting
        for long, short, key in pairs:
            try:
                result = await self.fetch_arbitrage_data(long, short, all_data=True)
                if result:
                    merged[key] = result
                    self._last_data = dict(merged)

                    # Trigger callback if set (for real-time basis alerting)
                    if self._on_pair_complete:
                        try:
                            await self._on_pair_complete(self._last_data)
                        except Exception as cb_exc:
                            logger.debug("on_pair_complete callback error: %s", cb_exc)
            except Exception as exc:
                logger.error("fetch_all_data failed for %s: %s", key, exc)

        self._last_data = merged
        return merged

    def get_cached_data(self) -> dict[str, Any]:
        """Return the last fetched data (updated every ~3s by realtime scheduler)."""
        return self._last_data


# Module-level singleton instance
data_fetcher = DataFetcher()
