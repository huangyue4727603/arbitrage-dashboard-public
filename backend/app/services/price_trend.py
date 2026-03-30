import asyncio
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.database import async_session_factory
from app.models.market_data import PriceKline, PriceTrend
from app.services.exchange.binance import BinanceClient

logger = logging.getLogger(__name__)

# Timeframe definitions: (label, kline_interval, weight for sorting)
TIMEFRAMES = [
    ("1d", "1d", 8),
    ("4h", "4h", 4),
    ("1h", "1h", 2),
    ("15m", "15m", 1),
]


class PriceTrendService:
    """Calculate moving averages and detect bullish alignment using DB kline data."""

    def __init__(self) -> None:
        self._symbols_cache: Optional[List[str]] = None

    async def _get_all_usdt_perp_symbols(self) -> List[str]:
        """Get all USDT perpetual contract symbols from Binance."""
        if self._symbols_cache is not None:
            return self._symbols_cache

        async with BinanceClient() as client:
            info = await client.get_exchange_info()

        symbols: List[str] = []
        for s in info.get("symbols", []):
            if (
                s.get("contractType") == "PERPETUAL"
                and s.get("quoteAsset") == "USDT"
                and s.get("status") == "TRADING"
            ):
                symbols.append(s["symbol"])

        self._symbols_cache = symbols
        logger.info("Cached %d USDT perp symbols from Binance", len(symbols))
        return symbols

    async def _check_bullish_from_db(self, symbol: str, interval: str) -> bool:
        """Check bullish MA alignment from DB kline data.

        Returns True if: current_price > MA20 > MA60 > MA120
        """
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(PriceKline.close_price)
                    .where(PriceKline.symbol == symbol)
                    .where(PriceKline.interval_type == interval)
                    .order_by(PriceKline.kline_time.desc())
                    .limit(120)
                )
                rows = result.scalars().all()

            if len(rows) < 120:
                return False

            # rows are desc order, reverse to chronological
            closes = list(reversed(rows))

            current_price = closes[-1]
            ma20 = sum(closes[-20:]) / 20
            ma60 = sum(closes[-60:]) / 60
            ma120 = sum(closes[-120:]) / 120

            return current_price > ma20 > ma60 > ma120
        except Exception as exc:
            logger.debug("Failed to check bullish for %s %s: %s", symbol, interval, exc)
            return False

    async def _get_latest_price_from_db(self, symbol: str) -> Optional[float]:
        """Get the latest price from 5m kline data."""
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(PriceKline.close_price)
                    .where(PriceKline.symbol == symbol)
                    .where(PriceKline.interval_type == "5m")
                    .order_by(PriceKline.kline_time.desc())
                    .limit(1)
                )
                row = result.scalar_one_or_none()
                return row
        except Exception:
            return None

    async def _check_bullish_from_db_with_price(self, symbol: str, interval: str, current_price: float) -> bool:
        """Check bullish MA alignment using DB kline data + real-time price from 5m.

        Returns True if: current_price > MA20 > MA60 > MA120
        """
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(PriceKline.close_price)
                    .where(PriceKline.symbol == symbol)
                    .where(PriceKline.interval_type == interval)
                    .order_by(PriceKline.kline_time.desc())
                    .limit(120)
                )
                rows = result.scalars().all()

            if len(rows) < 120:
                return False

            closes = list(reversed(rows))

            ma20 = sum(closes[-20:]) / 20
            ma60 = sum(closes[-60:]) / 60
            ma120 = sum(closes[-120:]) / 120

            return current_price > ma20 > ma60 > ma120
        except Exception as exc:
            logger.debug("Failed to check bullish for %s %s: %s", symbol, interval, exc)
            return False

    async def _process_symbol(self, symbol: str, semaphore: asyncio.Semaphore) -> Optional[Dict[str, Any]]:
        """Process a single symbol across all timeframes using DB data."""
        async with semaphore:
            try:
                # Use latest 5m close as real-time price for all timeframes
                current_price = await self._get_latest_price_from_db(symbol)
                if current_price is None:
                    return None

                results: Dict[str, bool] = {}
                for label, interval, _ in TIMEFRAMES:
                    results[label] = await self._check_bullish_from_db_with_price(symbol, interval, current_price)

                if not any(results.values()):
                    return None

                sort_score = 0
                highest_weight = 0
                for label, _, weight in TIMEFRAMES:
                    if results[label]:
                        sort_score += weight
                        highest_weight = max(highest_weight, weight)

                coin_name = symbol[:-4] if symbol.endswith("USDT") else symbol

                return {
                    "coin_name": coin_name,
                    "daily": results["1d"],
                    "h4": results["4h"],
                    "h1": results["1h"],
                    "m15": results["15m"],
                    "sort_score": highest_weight * 100 + sort_score,
                }
            except Exception as exc:
                logger.error("Error processing %s: %s", symbol, exc)
                return None

    async def calculate_all(self) -> List[Dict[str, Any]]:
        """Calculate bullish alignment for all symbols from DB kline data."""
        symbols = await self._get_all_usdt_perp_symbols()
        logger.info("Processing %d symbols for price trend...", len(symbols))

        semaphore = asyncio.Semaphore(20)

        tasks = [self._process_symbol(symbol, semaphore) for symbol in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        trend_list: List[Dict[str, Any]] = []
        for r in results:
            if isinstance(r, Exception):
                logger.error("Task exception: %s", r)
                continue
            if r is not None:
                trend_list.append(r)

        trend_list.sort(key=lambda x: x["sort_score"], reverse=True)

        # Save to DB
        await self._save_to_db(trend_list)

        logger.info("Price trend calculation complete: %d coins with bullish alignment", len(trend_list))
        return trend_list

    async def _save_to_db(self, trend_list: List[Dict[str, Any]]) -> None:
        """Upsert price trend results to DB."""
        if not trend_list:
            return
        async with async_session_factory() as db:
            try:
                for item in trend_list:
                    stmt = mysql_insert(PriceTrend).values(
                        coin_name=item["coin_name"],
                        daily=item["daily"],
                        h4=item["h4"],
                        h1=item["h1"],
                        m15=item["m15"],
                        sort_score=item["sort_score"],
                    )
                    stmt = stmt.on_duplicate_key_update(
                        daily=stmt.inserted.daily,
                        h4=stmt.inserted.h4,
                        h1=stmt.inserted.h1,
                        m15=stmt.inserted.m15,
                        sort_score=stmt.inserted.sort_score,
                    )
                    await db.execute(stmt)
                await db.commit()
                logger.info("Saved %d price trends to DB", len(trend_list))
            except Exception as exc:
                logger.error("Failed to save price trends: %s", exc)
                await db.rollback()
