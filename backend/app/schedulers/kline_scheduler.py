import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import delete, select, func

from app.database import async_session_factory
from app.models.market_data import PriceKline, FundingHistory
from app.services.exchange.binance import BinanceClient
from app.services.exchange.okx import OKXClient
from app.services.exchange.bybit import BybitClient
from app.services.binance_kline_ws import binance_kline_ws
from app.services.okx_kline_ws import okx_kline_ws
from app.services.bybit_kline_ws import bybit_kline_ws

logger = logging.getLogger(__name__)

# Intervals and their data retention periods
KLINE_INTERVALS = {
    "5m": {"retention_hours": 80},
    "15m": {"retention_hours": 48},
    "1h": {"retention_hours": 168},      # 7 days
    "4h": {"retention_hours": 720},      # 30 days
    "1d": {"retention_hours": 4320},     # 180 days
}


class KlineScheduler:
    """Scheduler for kline data.

    Data ingestion is handled by BinanceKlineWS (WebSocket streams).
    This scheduler is responsible for:
    - Starting/stopping the WebSocket subscriber
    - Computing derived metrics (price changes, funding cumulative)
    - Cleaning up old data
    """

    def __init__(self) -> None:
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._symbols_cache: Optional[list[str]] = None
        self._price_changes: dict[str, dict[str, Any]] = {}
        self._funding_cumulative: dict[str, dict[str, Any]] = {}

    async def _get_symbols(self) -> list[str]:
        """Get all USDT perpetual symbols from Binance, with DB fallback."""
        if self._symbols_cache:
            return self._symbols_cache
        try:
            async with BinanceClient() as client:
                info = await client.get_exchange_info()
            if info:
                symbols = []
                for s in info.get("symbols", []):
                    if (
                        s.get("contractType") in ("PERPETUAL", "TRADIFI_PERPETUAL")
                        and s.get("quoteAsset") == "USDT"
                        and s.get("status") == "TRADING"
                    ):
                        symbols.append(s["symbol"])
                if symbols:
                    self._symbols_cache = symbols
                    logger.info("Kline scheduler: cached %d symbols from API", len(symbols))
                    return symbols
        except Exception as exc:
            logger.warning("Failed to get symbols from API: %s", exc)

        # Fallback: get symbols from existing DB kline data
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(PriceKline.symbol).distinct()
                )
                symbols = [row[0] for row in result.all()]
            if symbols:
                self._symbols_cache = symbols
                logger.info("Kline scheduler: cached %d symbols from DB (API unavailable)", len(symbols))
                return symbols
        except Exception as exc:
            logger.error("Failed to get symbols from DB: %s", exc)
        return []

    # ------------------------------------------------------------------
    # WebSocket lifecycle
    # ------------------------------------------------------------------

    async def _start_ws(self) -> None:
        """Start kline WebSocket subscribers for all exchanges."""
        # Binance
        symbols = await self._get_symbols()
        if symbols:
            await binance_kline_ws.start(symbols)
        else:
            logger.error("No Binance symbols, cannot start Binance kline WS")

        # OKX — get all USDT-SWAP instrument IDs
        try:
            async with OKXClient() as client:
                tickers = await client.get_tickers(inst_type="SWAP")
            okx_ids = [
                t["instId"] for t in tickers
                if t.get("instId", "").endswith("-USDT-SWAP")
            ]
            if okx_ids:
                await okx_kline_ws.start(okx_ids)
            else:
                logger.warning("No OKX instruments found for kline WS")
        except Exception as exc:
            logger.error("Failed to start OKX kline WS: %s", exc)

        # Bybit — get all USDT linear perpetual symbols
        try:
            async with BybitClient() as client:
                instruments = await client.get_instruments_info(category="linear")
            bybit_symbols = [
                inst["symbol"] for inst in instruments
                if inst.get("settleCoin") == "USDT"
                and inst.get("status") == "Trading"
                and inst.get("contractType") == "LinearPerpetual"
            ]
            if bybit_symbols:
                await bybit_kline_ws.start(bybit_symbols)
            else:
                logger.warning("No Bybit instruments found for kline WS")
        except Exception as exc:
            logger.error("Failed to start Bybit kline WS: %s", exc)

    async def _cleanup_old_data(self) -> None:
        """Delete klines older than their retention period."""
        async with async_session_factory() as db:
            try:
                for interval, config in KLINE_INTERVALS.items():
                    cutoff = datetime.now() - timedelta(hours=config["retention_hours"])
                    await db.execute(
                        delete(PriceKline)
                        .where(PriceKline.interval_type == interval)
                        .where(PriceKline.kline_time < cutoff)
                    )
                await db.commit()
            except Exception as exc:
                logger.error("Failed to cleanup old klines: %s", exc)
                await db.rollback()

    async def refresh_price_changes(self) -> None:
        """Compute 1d/3d price changes from DB kline data only (no API calls)."""
        try:
            changes: dict[str, dict[str, Any]] = {}

            # --- 24h change: from DB 5m klines (latest vs 24h ago) ---
            try:
                now = datetime.now()
                t_24h = now - timedelta(hours=24)
                async with async_session_factory() as db:
                    # Latest 5m close per symbol
                    latest_subq = (
                        select(PriceKline.symbol, func.max(PriceKline.kline_time).label("mt"))
                        .where(PriceKline.interval_type == "5m")
                        .group_by(PriceKline.symbol)
                        .subquery()
                    )
                    latest_res = await db.execute(
                        select(PriceKline.symbol, PriceKline.close_price)
                        .join(latest_subq, (PriceKline.symbol == latest_subq.c.symbol) &
                              (PriceKline.kline_time == latest_subq.c.mt))
                        .where(PriceKline.interval_type == "5m")
                    )
                    latest_prices = {row[0]: row[1] for row in latest_res.all()}

                    # 24h ago close (nearest 5m candle in ±30min window)
                    lo, hi = t_24h - timedelta(minutes=30), t_24h + timedelta(minutes=30)
                    old_subq = (
                        select(PriceKline.symbol, func.max(PriceKline.kline_time).label("nt"))
                        .where(PriceKline.interval_type == "5m")
                        .where(PriceKline.kline_time.between(lo, hi))
                        .group_by(PriceKline.symbol)
                        .subquery()
                    )
                    old_res = await db.execute(
                        select(PriceKline.symbol, PriceKline.close_price)
                        .join(old_subq, (PriceKline.symbol == old_subq.c.symbol) &
                              (PriceKline.kline_time == old_subq.c.nt))
                        .where(PriceKline.interval_type == "5m")
                    )
                    old_prices = {row[0]: row[1] for row in old_res.all()}

                for symbol, current in latest_prices.items():
                    old = old_prices.get(symbol)
                    if old and old > 0:
                        coin = symbol[:-4] if symbol.endswith("USDT") else symbol
                        changes[coin] = {"change_1d": round((current - old) / old * 100, 2)}
                logger.info("24h price changes from DB 5m klines: %d coins", len(changes))
            except Exception as exc:
                logger.error("Failed to compute 24h changes: %s", exc)

            # --- 3d: current price from 5m kline, 72h-ago price from 1d kline ---
            try:
                now = datetime.now()
                t_3d = now - timedelta(hours=72)

                async with async_session_factory() as db:
                    # Current price: latest 5m kline close (most up-to-date)
                    # Reuse latest_prices from 24h calc above if available
                    if not latest_prices:
                        latest_5m_subq = (
                            select(PriceKline.symbol, func.max(PriceKline.kline_time).label("mt"))
                            .where(PriceKline.interval_type == "5m")
                            .group_by(PriceKline.symbol)
                            .subquery()
                        )
                        latest_5m_res = await db.execute(
                            select(PriceKline.symbol, PriceKline.close_price)
                            .join(latest_5m_subq, (PriceKline.symbol == latest_5m_subq.c.symbol) &
                                  (PriceKline.kline_time == latest_5m_subq.c.mt))
                            .where(PriceKline.interval_type == "5m")
                        )
                        latest_prices = {row[0]: row[1] for row in latest_5m_res.all()}

                    # 72h ago: 1d kline (±1 day window)
                    lo = t_3d - timedelta(days=1)
                    hi = t_3d + timedelta(days=1)
                    subq_3d = (
                        select(
                            PriceKline.symbol,
                            func.max(PriceKline.kline_time).label("nearest_time"),
                        )
                        .where(PriceKline.interval_type == "1d")
                        .where(PriceKline.kline_time.between(lo, hi))
                        .group_by(PriceKline.symbol)
                        .subquery()
                    )
                    result_3d = await db.execute(
                        select(PriceKline.symbol, PriceKline.close_price)
                        .where(PriceKline.interval_type == "1d")
                        .join(subq_3d, (PriceKline.symbol == subq_3d.c.symbol) &
                              (PriceKline.kline_time == subq_3d.c.nearest_time))
                    )
                    prices_3d = {row[0]: row[1] for row in result_3d.all()}

                for symbol, current in latest_prices.items():
                    coin = symbol[:-4] if symbol.endswith("USDT") else symbol
                    old_3d = prices_3d.get(symbol)
                    if old_3d and old_3d > 0:
                        change_3d = round((current - old_3d) / old_3d * 100, 2)
                        if coin in changes:
                            changes[coin]["change_3d"] = change_3d
                        else:
                            changes[coin] = {"change_3d": change_3d}
                logger.info("3d price changes from DB: %d coins", len(prices_3d))
            except Exception as exc:
                logger.error("Failed to compute 3d changes: %s", exc)

            self._price_changes = changes
            logger.info("Price changes computed: %d coins total", len(changes))
        except Exception as exc:
            logger.error("Failed to compute price changes: %s", exc)

    async def refresh_funding_cumulative(self) -> None:
        """Compute 1d/3d cumulative funding rates from DB (per coin+exchange)."""
        try:
            now = datetime.now()
            t_1d = now - timedelta(hours=24)
            t_3d = now - timedelta(hours=72)

            async with async_session_factory() as db:
                # 1d cumulative: sum of funding_rate in last 24h per (coin, exchange)
                result_1d = await db.execute(
                    select(
                        FundingHistory.coin,
                        FundingHistory.exchange,
                        func.sum(FundingHistory.funding_rate).label("total"),
                    )
                    .where(FundingHistory.funding_time >= t_1d)
                    .group_by(FundingHistory.coin, FundingHistory.exchange)
                )
                cum_1d = {}
                for row in result_1d.all():
                    key = f"{row[0]}_{row[1]}"
                    cum_1d[key] = round(row[2] * 100, 3)

                # 3d cumulative
                result_3d = await db.execute(
                    select(
                        FundingHistory.coin,
                        FundingHistory.exchange,
                        func.sum(FundingHistory.funding_rate).label("total"),
                    )
                    .where(FundingHistory.funding_time >= t_3d)
                    .group_by(FundingHistory.coin, FundingHistory.exchange)
                )
                cum_3d = {}
                for row in result_3d.all():
                    key = f"{row[0]}_{row[1]}"
                    cum_3d[key] = round(row[2] * 100, 3)

            # Merge into single dict
            all_keys = set(cum_1d.keys()) | set(cum_3d.keys())
            result: dict[str, dict[str, Any]] = {}
            for key in all_keys:
                entry: dict[str, Any] = {}
                if key in cum_1d:
                    entry["funding_1d"] = cum_1d[key]
                if key in cum_3d:
                    entry["funding_3d"] = cum_3d[key]
                result[key] = entry

            self._funding_cumulative = result
            logger.info("Funding cumulative computed: %d coin-exchange pairs", len(result))
        except Exception as exc:
            logger.error("Failed to compute funding cumulative: %s", exc)

    def get_price_changes(self) -> dict[str, dict[str, Any]]:
        """Return cached price changes."""
        return self._price_changes

    def get_funding_cumulative(self) -> dict[str, dict[str, Any]]:
        """Return cached funding cumulative data."""
        return self._funding_cumulative

    def start(self) -> None:
        """Start WebSocket subscriber and periodic computation jobs."""
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()

        # Start kline WebSocket (delayed to allow DB init)
        self._scheduler.add_job(
            self._start_ws,
            id="kline_ws_start",
            name="Start kline WebSocket",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=5),
        )

        # Price changes refresh every 5 minutes (from DB, no API calls)
        self._scheduler.add_job(
            self.refresh_price_changes,
            trigger=IntervalTrigger(minutes=5),
            id="price_changes_refresh",
            name="Compute price changes",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=15),
        )

        # Funding cumulative refresh every 5 minutes (DB query)
        self._scheduler.add_job(
            self.refresh_funding_cumulative,
            trigger=IntervalTrigger(minutes=5),
            id="funding_cumulative_refresh",
            name="Compute funding cumulative",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(seconds=12),
        )

        # Cleanup old kline data every hour
        self._scheduler.add_job(
            self._cleanup_old_data,
            trigger=IntervalTrigger(hours=1),
            id="kline_cleanup",
            name="Cleanup old kline data",
            replace_existing=True,
            next_run_time=datetime.now() + timedelta(minutes=5),
        )

        self._scheduler.start()
        logger.info("Kline scheduler started (WebSocket mode)")

    def stop(self) -> None:
        """Stop the scheduler and all WebSocket connections."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None

        # Stop all WebSocket connections in background (can't await in sync method)
        import asyncio
        async def _stop_all():
            await binance_kline_ws.stop()
            await okx_kline_ws.stop()
            await bybit_kline_ws.stop()

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_stop_all())
            else:
                loop.run_until_complete(_stop_all())
        except Exception:
            pass
        logger.info("Kline scheduler stopped (WebSocket mode)")


# Module-level singleton
kline_scheduler = KlineScheduler()
