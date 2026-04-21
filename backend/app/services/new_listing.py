import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.database import async_session_factory
from app.models.market_data import NewListing
from app.services.exchange import BinanceClient, OKXClient, BybitClient
from app.services.okx_kline_ws import okx_kline_ws
from app.services.bybit_kline_ws import bybit_kline_ws

logger = logging.getLogger(__name__)

# 90 days in milliseconds
NINETY_DAYS_MS = 90 * 24 * 60 * 60 * 1000


class NewListingService:
    """Service for detecting and tracking newly listed coins on exchanges.

    Maintains a per-exchange set of symbols confirmed to be older than 90 days.
    These are skipped on subsequent refreshes to avoid unnecessary API calls.
    """

    def __init__(self) -> None:
        # Symbols confirmed >90 days old — never need kline check again
        self._old_symbols: dict[str, set[str]] = {
            "BINANCE": set(),
            "OKX": set(),
            "BYBIT": set(),
        }

    async def get_new_listings(self, exchange: str) -> list[dict[str, Any]]:
        """
        Get coins listed within the last 90 days on the given exchange.
        """
        exchange_upper = exchange.upper()
        if exchange_upper == "BINANCE":
            return await self._get_binance_new_listings()
        elif exchange_upper == "OKX":
            return await self._get_okx_new_listings()
        elif exchange_upper == "BYBIT":
            return await self._get_bybit_new_listings()
        else:
            logger.error("Unknown exchange: %s", exchange)
            return []

    async def save_to_db(self, exchange: str, listings: list[dict[str, Any]]) -> None:
        """Save new listing data to DB using upsert."""
        if not listings:
            return
        async with async_session_factory() as db:
            try:
                for item in listings:
                    coin_name = item.get("coin_name", "")
                    symbol = f"{coin_name}USDT"
                    listing_time = None
                    if item.get("listing_time_ms"):
                        listing_time = datetime.fromtimestamp(item["listing_time_ms"] / 1000)

                    stmt = mysql_insert(NewListing).values(
                        exchange=exchange.upper(),
                        symbol=symbol,
                        coin_name=coin_name,
                        listing_time=listing_time,
                        listing_days=item.get("listing_days"),
                        current_funding_rate=item.get("current_funding_rate"),
                        settlement_period=item.get("settlement_period", 8),
                        price_change=item.get("price_change"),
                    )
                    stmt = stmt.on_duplicate_key_update(
                        coin_name=stmt.inserted.coin_name,
                        listing_time=stmt.inserted.listing_time,
                        listing_days=stmt.inserted.listing_days,
                        current_funding_rate=stmt.inserted.current_funding_rate,
                        settlement_period=stmt.inserted.settlement_period,
                        price_change=stmt.inserted.price_change,
                    )
                    await db.execute(stmt)
                await db.commit()
                logger.info("Saved %d new listings for %s to DB", len(listings), exchange)
            except Exception as exc:
                logger.error("Failed to save new listings for %s: %s", exchange, exc)
                await db.rollback()

    async def get_from_db(self, exchange: str) -> list[dict[str, Any]]:
        """Load new listings from DB."""
        # Map DB exchange names to short names
        ex_short = {"BINANCE": "BN", "OKX": "OKX", "BYBIT": "BY"}
        async with async_session_factory() as db:
            result = await db.execute(
                select(NewListing)
                .where(NewListing.exchange == exchange.upper())
                .order_by(NewListing.listing_days.asc())
            )
            rows = result.scalars().all()
            return [
                {
                    "coin_name": r.coin_name,
                    "exchange": ex_short.get(r.exchange, r.exchange),
                    "listing_days": r.listing_days,
                    "current_funding_rate": r.current_funding_rate,
                    "settlement_period": r.settlement_period or 8,
                    "price_change": r.price_change,
                }
                for r in rows
            ]

    async def _get_binance_new_listings(self) -> list[dict[str, Any]]:
        """Get new listings from Binance using kline data."""
        results: list[dict[str, Any]] = []
        now_ms = int(time.time() * 1000)
        ninety_days_ago_ms = now_ms - NINETY_DAYS_MS
        old_symbols = self._old_symbols["BINANCE"]

        async with BinanceClient() as client:
            # Get all USDT perpetual symbols
            exchange_info = await client.get_exchange_info()
            symbols_info = exchange_info.get("symbols", [])
            usdt_perp_symbols = [
                s["symbol"]
                for s in symbols_info
                if s.get("contractType") == "PERPETUAL"
                and s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"
            ]

            # Skip symbols already confirmed >90 days
            symbols_to_check = [s for s in usdt_perp_symbols if s not in old_symbols]
            skipped = len(usdt_perp_symbols) - len(symbols_to_check)
            if skipped > 0:
                logger.info("Binance new listing: skipping %d known old symbols, checking %d",
                            skipped, len(symbols_to_check))

            # Get current funding rates for all symbols in one batch call
            all_tickers = await client.get_24hr_ticker()
            ticker_map: dict[str, dict[str, Any]] = {}
            if isinstance(all_tickers, list):
                for t in all_tickers:
                    ticker_map[t.get("symbol", "")] = t

            # Get funding info for settlement intervals
            funding_info_list = await client.get_funding_info()
            funding_info_map: dict[str, dict[str, Any]] = {}
            for fi in funding_info_list:
                funding_info_map[fi.get("symbol", "")] = fi

            # Check each symbol's kline data concurrently in batches
            semaphore = asyncio.Semaphore(3)

            async def check_symbol(symbol: str) -> Optional[dict[str, Any]]:
                async with semaphore:
                    try:
                        klines = await client.get_klines(
                            symbol=symbol,
                            interval="1d",
                            start_time=ninety_days_ago_ms,
                            limit=91,
                        )
                        if not klines or len(klines) >= 90:
                            # Confirmed old symbol — cache it
                            old_symbols.add(symbol)
                            return None

                        # It's a new listing
                        first_kline = klines[0]
                        first_day_close = float(first_kline[4])  # close price
                        open_time_ms = int(first_kline[0])

                        listing_days = (now_ms - open_time_ms) // (24 * 60 * 60 * 1000)

                        # Get current price from ticker
                        ticker = ticker_map.get(symbol, {})
                        current_price = float(ticker.get("lastPrice", 0))

                        # Price change
                        price_change: Optional[float] = None
                        if listing_days > 0 and first_day_close > 0 and current_price > 0:
                            price_change = round(
                                (current_price - first_day_close) / first_day_close * 100,
                                2,
                            )

                        # Get current funding rate from the latest funding rate history
                        funding_records = await client.get_funding_rate_history(
                            symbol=symbol, limit=1
                        )
                        current_funding_rate: Optional[float] = None
                        if funding_records:
                            current_funding_rate = round(
                                float(funding_records[0].get("fundingRate", 0)) * 100, 3
                            )

                        # Extract coin name from symbol (e.g., BTCUSDT -> BTC)
                        coin_name = symbol.replace("USDT", "")

                        # Settlement period from funding info
                        fi = funding_info_map.get(symbol, {})
                        settlement_period = fi.get("fundingIntervalHours", 8)

                        # 1d price change from 24hr ticker
                        change_1d: Optional[float] = None
                        pct = ticker.get("priceChangePercent")
                        if pct is not None:
                            change_1d = round(float(pct), 2)

                        return {
                            "coin_name": coin_name,
                            "exchange": "BN",
                            "listing_days": listing_days,
                            "current_funding_rate": current_funding_rate,
                            "settlement_period": settlement_period,
                            "price_change": price_change,
                            "change_1d": change_1d,
                            "listing_time_ms": open_time_ms,
                        }
                    except Exception as exc:
                        logger.warning("Binance check %s failed: %s", symbol, exc)
                        return None

            tasks = [check_symbol(s) for s in symbols_to_check]
            check_results = await asyncio.gather(*tasks)
            for r in check_results:
                if r is not None:
                    results.append(r)

        # Sort by listing time, newest first
        results.sort(key=lambda x: x["listing_time_ms"], reverse=True)
        # Remove internal sorting key
        for r in results:
            r.pop("listing_time_ms", None)
        return results

    async def _get_okx_new_listings(self) -> list[dict[str, Any]]:
        """Get new listings from OKX."""
        results: list[dict[str, Any]] = []
        now_ms = int(time.time() * 1000)
        ninety_days_ago_ms = now_ms - NINETY_DAYS_MS
        old_symbols = self._old_symbols["OKX"]

        async with OKXClient() as client:
            # Get all USDT swap tickers (this gives us the list of instruments)
            all_tickers = await client.get_tickers(inst_type="SWAP")
            usdt_swap_tickers = [
                t for t in all_tickers if t.get("instId", "").endswith("-USDT-SWAP")
            ]

            # Build ticker map
            ticker_map: dict[str, dict[str, Any]] = {}
            for t in usdt_swap_tickers:
                ticker_map[t.get("instId", "")] = t

            all_inst_ids = [t["instId"] for t in usdt_swap_tickers]

            # Also mark symbols with enough WS kline data as old
            ws_cached = okx_kline_ws.get_cached_symbols()
            for iid in all_inst_ids:
                if iid not in old_symbols and okx_kline_ws.get_kline_count(iid) >= 90:
                    old_symbols.add(iid)

            # Skip symbols already confirmed >90 days
            inst_ids = [iid for iid in all_inst_ids if iid not in old_symbols]
            skipped = len(all_inst_ids) - len(inst_ids)
            if skipped > 0:
                logger.info("OKX new listing: skipping %d known old symbols, checking %d",
                            skipped, len(inst_ids))

            semaphore = asyncio.Semaphore(3)

            async def check_inst(inst_id: str) -> Optional[dict[str, Any]]:
                async with semaphore:
                    try:
                        # OKX candles: returns newest first, limit=100 gets last 100 days
                        klines = await client.get_candles(
                            inst_id=inst_id,
                            bar="1D",
                            limit=100,
                        )
                        if not klines:
                            return None

                        # OKX klines are returned newest first, sort chronologically
                        klines_sorted = sorted(klines, key=lambda x: int(x[0]))

                        # Check if the oldest candle is within 90 days
                        oldest_ts = int(klines_sorted[0][0])
                        if oldest_ts < ninety_days_ago_ms:
                            # Confirmed old symbol — cache it
                            old_symbols.add(inst_id)
                            return None
                        first_kline = klines_sorted[0]
                        first_day_close = float(first_kline[4])  # close price at index 4
                        open_time_ms = int(first_kline[0])

                        listing_days = (now_ms - open_time_ms) // (24 * 60 * 60 * 1000)

                        # Current price from ticker
                        ticker = ticker_map.get(inst_id, {})
                        current_price = float(ticker.get("last", 0))

                        # Price change
                        price_change: Optional[float] = None
                        if listing_days > 0 and first_day_close > 0 and current_price > 0:
                            price_change = round(
                                (current_price - first_day_close) / first_day_close * 100,
                                2,
                            )

                        # Current funding rate
                        funding_data = await client.get_funding_rate(inst_id=inst_id)
                        current_funding_rate: Optional[float] = None
                        if funding_data:
                            rate_str = funding_data.get("fundingRate", "0")
                            current_funding_rate = round(float(rate_str) * 100, 3)

                        # Extract coin name (e.g., BTC-USDT-SWAP -> BTC)
                        coin_name = inst_id.split("-")[0]

                        # 1d price change from ticker
                        change_1d: Optional[float] = None
                        open_24h = float(ticker.get("open24h", 0) or 0)
                        if current_price > 0 and open_24h > 0:
                            change_1d = round((current_price - open_24h) / open_24h * 100, 2)

                        return {
                            "coin_name": coin_name,
                            "exchange": "OKX",
                            "listing_days": listing_days,
                            "current_funding_rate": current_funding_rate,
                            "settlement_period": 8,
                            "price_change": price_change,
                            "change_1d": change_1d,
                            "listing_time_ms": open_time_ms,
                        }
                    except Exception as exc:
                        logger.warning("OKX check %s failed: %s", inst_id, exc)
                        return None

            tasks = [check_inst(iid) for iid in inst_ids]
            check_results = await asyncio.gather(*tasks)
            for r in check_results:
                if r is not None:
                    results.append(r)

        results.sort(key=lambda x: x["listing_time_ms"], reverse=True)
        for r in results:
            r.pop("listing_time_ms", None)
        return results

    async def _get_bybit_new_listings(self) -> list[dict[str, Any]]:
        """Get new listings from Bybit."""
        results: list[dict[str, Any]] = []
        now_ms = int(time.time() * 1000)
        ninety_days_ago_ms = now_ms - NINETY_DAYS_MS
        old_symbols = self._old_symbols["BYBIT"]

        async with BybitClient() as client:
            # Get all linear USDT perpetual instruments
            instruments = await client.get_instruments_info(category="linear")
            usdt_perps = [
                inst
                for inst in instruments
                if inst.get("settleCoin") == "USDT"
                and inst.get("status") == "Trading"
                and inst.get("contractType") == "LinearPerpetual"
            ]

            # Get all tickers for current prices and funding rates
            all_tickers = await client.get_tickers(category="linear")
            ticker_map: dict[str, dict[str, Any]] = {}
            for t in all_tickers:
                ticker_map[t.get("symbol", "")] = t

            all_symbols = [inst["symbol"] for inst in usdt_perps]

            # Also mark symbols with enough WS kline data as old
            for s in all_symbols:
                if s not in old_symbols and bybit_kline_ws.get_kline_count(s) >= 90:
                    old_symbols.add(s)

            # Skip symbols already confirmed >90 days
            symbols = [s for s in all_symbols if s not in old_symbols]
            skipped = len(all_symbols) - len(symbols)
            if skipped > 0:
                logger.info("Bybit new listing: skipping %d known old symbols, checking %d",
                            skipped, len(symbols))

            semaphore = asyncio.Semaphore(3)

            async def check_symbol(symbol: str) -> Optional[dict[str, Any]]:
                async with semaphore:
                    try:
                        # Bybit kline: interval "D", start = 90 days ago
                        klines = await client.get_kline(
                            symbol=symbol,
                            interval="D",
                            start=ninety_days_ago_ms,
                            limit=91,
                        )
                        if not klines or len(klines) >= 90:
                            # Confirmed old symbol — cache it
                            old_symbols.add(symbol)
                            return None

                        # Bybit klines are returned newest first, sort chronologically
                        klines_sorted = sorted(klines, key=lambda x: int(x[0]))
                        first_kline = klines_sorted[0]
                        first_day_close = float(first_kline[4])  # close price at index 4
                        open_time_ms = int(first_kline[0])

                        listing_days = (now_ms - open_time_ms) // (24 * 60 * 60 * 1000)

                        # Current price and funding rate from ticker
                        ticker = ticker_map.get(symbol, {})
                        current_price = float(ticker.get("lastPrice", 0))

                        # Price change
                        price_change: Optional[float] = None
                        if listing_days > 0 and first_day_close > 0 and current_price > 0:
                            price_change = round(
                                (current_price - first_day_close) / first_day_close * 100,
                                2,
                            )

                        # Current funding rate from ticker
                        current_funding_rate: Optional[float] = None
                        funding_rate_str = ticker.get("fundingRate", "")
                        if funding_rate_str:
                            current_funding_rate = round(
                                float(funding_rate_str) * 100, 3
                            )

                        # Extract coin name (e.g., BTCUSDT -> BTC)
                        coin_name = symbol.replace("USDT", "")

                        # 1d price change from ticker
                        change_1d: Optional[float] = None
                        prev_price = float(ticker.get("prevPrice24h", 0) or 0)
                        if current_price > 0 and prev_price > 0:
                            change_1d = round((current_price - prev_price) / prev_price * 100, 2)

                        return {
                            "coin_name": coin_name,
                            "exchange": "BY",
                            "listing_days": listing_days,
                            "current_funding_rate": current_funding_rate,
                            "settlement_period": 8,
                            "price_change": price_change,
                            "change_1d": change_1d,
                            "listing_time_ms": open_time_ms,
                        }
                    except Exception as exc:
                        logger.warning("Bybit check %s failed: %s", symbol, exc)
                        return None

            tasks = [check_symbol(s) for s in symbols]
            check_results = await asyncio.gather(*tasks)
            for r in check_results:
                if r is not None:
                    results.append(r)

        results.sort(key=lambda x: x["listing_time_ms"], reverse=True)
        for r in results:
            r.pop("listing_time_ms", None)
        return results


# Module-level singleton
new_listing_service = NewListingService()
