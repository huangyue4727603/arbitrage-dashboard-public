import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

from sqlalchemy import select

# UTC+8 timezone
_UTC8 = timezone(timedelta(hours=8))

from app.database import async_session_factory
from app.models.market_data import FundingHistory, FundingCap
from app.services.exchange.binance import BinanceClient
from app.services.exchange.okx import OKXClient
from app.services.exchange.bybit import BybitClient

logger = logging.getLogger(__name__)

# Exchange key constants
BINANCE = "BN"
OKX = "OKX"
BYBIT = "BY"

# The 6 ranking boards: (long_exchange, short_exchange)
BOARDS = [
    (OKX, BINANCE),    # OKX多 BN空
    (BYBIT, BINANCE),  # BY多 BN空
    (OKX, BYBIT),      # OKX多 BY空
    (BINANCE, OKX),    # BN多 OKX空
    (BINANCE, BYBIT),  # BN多 BY空
    (BYBIT, OKX),      # BY多 OKX空
]


def _coin_from_bn_symbol(symbol: str) -> Optional[str]:
    if symbol.endswith("USDT"):
        return symbol[:-4]
    return None


def _coin_from_okx_inst_id(inst_id: str) -> Optional[str]:
    parts = inst_id.split("-")
    if len(parts) >= 3 and parts[1] == "USDT" and parts[2] == "SWAP":
        return parts[0]
    return None


def _coin_from_bybit_symbol(symbol: str) -> Optional[str]:
    if symbol.endswith("USDT"):
        return symbol[:-4]
    return None


def _to_bn_symbol(coin: str) -> str:
    return f"{coin}USDT"


def _to_okx_inst_id(coin: str) -> str:
    return f"{coin}-USDT-SWAP"


def _to_bybit_symbol(coin: str) -> str:
    return f"{coin}USDT"


def _exchange_symbol(exchange: str, coin: str) -> str:
    if exchange == BINANCE:
        return _to_bn_symbol(coin)
    elif exchange == OKX:
        return _to_okx_inst_id(coin)
    elif exchange == BYBIT:
        return _to_bybit_symbol(coin)
    raise ValueError(f"Unknown exchange: {exchange}")


class FundingRankService:
    """Service for calculating funding rate rankings across exchange pairs."""

    # ── Exchange coin lists ──

    async def _get_exchange_coins(self, exchange: str) -> set[str]:
        coins: set[str] = set()
        if exchange == BINANCE:
            async with BinanceClient() as client:
                info = await client.get_exchange_info()
                for s in info.get("symbols", []):
                    if (
                        s.get("contractType") == "PERPETUAL"
                        and s.get("quoteAsset") == "USDT"
                        and s.get("status") == "TRADING"
                    ):
                        coin = _coin_from_bn_symbol(s["symbol"])
                        if coin:
                            coins.add(coin)
        elif exchange == OKX:
            async with OKXClient() as client:
                tickers = await client.get_tickers(inst_type="SWAP")
                for t in tickers:
                    coin = _coin_from_okx_inst_id(t.get("instId", ""))
                    if coin:
                        coins.add(coin)
        elif exchange == BYBIT:
            async with BybitClient() as client:
                instruments = await client.get_instruments_info()
                for inst in instruments:
                    if inst.get("status") == "Trading" and inst.get("quoteCoin") == "USDT":
                        coin = _coin_from_bybit_symbol(inst.get("symbol", ""))
                        if coin:
                            coins.add(coin)

        # DB fallback: if API returns empty (e.g. IP banned), read from DB
        if not coins:
            coins = await self._get_exchange_coins_from_db(exchange)
            if coins:
                logger.info("_get_exchange_coins(%s): API empty, using DB fallback (%d coins)",
                            exchange, len(coins))
        return coins

    async def _get_exchange_coins_from_db(self, exchange: str) -> set[str]:
        """Fallback: get coin list from funding_caps + funding_history tables."""
        exchange_cap_map = {BINANCE: "Binance", OKX: "OKX", BYBIT: "Bybit"}
        cap_name = exchange_cap_map.get(exchange, exchange)
        coins: set[str] = set()
        try:
            async with async_session_factory() as db:
                # From funding_caps
                from app.models.market_data import FundingCap
                result = await db.execute(
                    select(FundingCap.symbol).where(FundingCap.exchange == cap_name)
                )
                for row in result.all():
                    sym = row[0]
                    if sym.endswith("USDT"):
                        coins.add(sym[:-4])
                    elif "-" in sym:
                        coins.add(sym.split("-")[0])

                # Also from funding_history (catches coins not in caps)
                result2 = await db.execute(
                    select(FundingHistory.coin).where(FundingHistory.exchange == exchange).distinct()
                )
                for row in result2.all():
                    coins.add(row[0])
        except Exception as exc:
            logger.error("DB fallback for %s coins failed: %s", exchange, exc)
        return coins

    # ── API fetch methods (used by scheduler for data ingestion) ──

    async def _fetch_funding_history_bn(
        self, coin: str, start_time: int, end_time: int
    ) -> list[dict[str, Any]]:
        symbol = _to_bn_symbol(coin)
        all_records: list[dict[str, Any]] = []
        current_start = start_time
        async with BinanceClient() as client:
            while current_start < end_time:
                records = await client.get_funding_rate_history(
                    symbol=symbol, start_time=current_start, end_time=end_time, limit=1000,
                )
                if not records:
                    break
                all_records.extend(records)
                last_time = int(records[-1].get("fundingTime", 0))
                if last_time <= current_start:
                    break
                current_start = last_time + 1
        return all_records

    async def _fetch_funding_history_okx(
        self, coin: str, start_time: int, end_time: int
    ) -> list[dict[str, Any]]:
        inst_id = _to_okx_inst_id(coin)
        all_records: list[dict[str, Any]] = []
        async with OKXClient() as client:
            current_after = str(end_time)
            while True:
                records = await client.get_funding_rate_history(
                    inst_id=inst_id, before=str(start_time - 1), after=current_after, limit=100,
                )
                if not records:
                    break
                all_records.extend(records)
                oldest_time = min(int(r.get("fundingTime", "0")) for r in records)
                if oldest_time <= start_time:
                    break
                current_after = str(oldest_time)
        return all_records

    async def _fetch_funding_history_bybit(
        self, coin: str, start_time: int, end_time: int
    ) -> list[dict[str, Any]]:
        symbol = _to_bybit_symbol(coin)
        all_records: list[dict[str, Any]] = []
        async with BybitClient() as client:
            current_start = start_time
            while current_start < end_time:
                records = await client.get_funding_rate_history(
                    symbol=symbol, start_time=current_start, end_time=end_time, limit=200,
                )
                if not records:
                    break
                all_records.extend(records)
                newest_time = max(int(r.get("fundingRateTimestamp", "0")) for r in records)
                if len(records) < 200:
                    break
                current_start = newest_time + 1
        return all_records

    def _parse_funding_records(
        self, exchange: str, records: list[dict[str, Any]]
    ) -> list[dict[str, float]]:
        parsed = []
        for r in records:
            if exchange == BINANCE:
                t = int(r.get("fundingTime", 0))
                rate = float(r.get("fundingRate", 0))
            elif exchange == OKX:
                t = int(r.get("fundingTime", "0"))
                rate = float(r.get("fundingRate", "0"))
            elif exchange == BYBIT:
                t = int(r.get("fundingRateTimestamp", "0"))
                rate = float(r.get("fundingRate", "0"))
            else:
                continue
            parsed.append({"time_ms": t, "rate": rate})
        return parsed

    async def _fetch_funding_for_exchange(
        self, exchange: str, coin: str, start_time: int, end_time: int
    ) -> list[dict[str, float]]:
        if exchange == BINANCE:
            records = await self._fetch_funding_history_bn(coin, start_time, end_time)
        elif exchange == OKX:
            records = await self._fetch_funding_history_okx(coin, start_time, end_time)
        elif exchange == BYBIT:
            records = await self._fetch_funding_history_bybit(coin, start_time, end_time)
        else:
            return []
        return self._parse_funding_records(exchange, records)

    # ── Prices ──

    async def _get_prices(self, coins: list[str], exchange: str) -> dict[str, float]:
        prices: dict[str, float] = {}
        if exchange == BINANCE:
            async with BinanceClient() as client:
                tickers = await client.get_all_tickers()
                for t in tickers:
                    coin = _coin_from_bn_symbol(t.get("symbol", ""))
                    if coin and coin in coins:
                        prices[coin] = float(t.get("price", 0))
        elif exchange == OKX:
            async with OKXClient() as client:
                tickers = await client.get_tickers(inst_type="SWAP")
                for t in tickers:
                    coin = _coin_from_okx_inst_id(t.get("instId", ""))
                    if coin and coin in coins:
                        prices[coin] = float(t.get("last", 0))
        elif exchange == BYBIT:
            async with BybitClient() as client:
                tickers = await client.get_tickers()
                for t in tickers:
                    coin = _coin_from_bybit_symbol(t.get("symbol", ""))
                    if coin and coin in coins:
                        prices[coin] = float(t.get("lastPrice", 0))
        return prices

    # ── Funding calculation helpers ──

    def _calculate_funding_for_side(
        self, records: list[dict[str, float]], side: str
    ) -> tuple[float, int]:
        total = 0.0
        count = len(records)
        for r in records:
            rate = r["rate"]
            if side == "long":
                total += -rate
            else:
                total += rate
        return total, count

    # ── DB-based ranking / detail / statistics ──

    def _ms_to_dt(self, ms: int) -> datetime:
        """Convert millisecond timestamp to UTC+8 naive datetime."""
        return datetime.fromtimestamp(ms / 1000, tz=_UTC8).replace(tzinfo=None)

    def _dt_to_ms(self, dt: datetime) -> int:
        """Convert UTC+8 naive datetime to millisecond timestamp."""
        return int(dt.replace(tzinfo=_UTC8).timestamp() * 1000)

    # Mapping: funding rank short name -> funding_caps DB name
    _CAPS_EXCHANGE_MAP = {"BN": "Binance", "OKX": "OKX", "BY": "Bybit"}

    async def get_rankings(self, start_time: int, end_time: int) -> list[dict]:
        """Calculate unified ranking list from DB funding history."""
        start_dt = self._ms_to_dt(start_time)
        end_dt = self._ms_to_dt(end_time)

        async with async_session_factory() as db:
            result = await db.execute(
                select(FundingHistory)
                .where(FundingHistory.funding_time >= start_dt)
                .where(FundingHistory.funding_time <= end_dt)
            )
            all_records = result.scalars().all()

            # Load settlement periods from funding_caps
            caps_result = await db.execute(select(FundingCap))
            caps_rows = caps_result.scalars().all()

        # Build settlement period map: (caps_exchange, coin) -> interval_hours
        settlement_map: dict[tuple[str, str], int] = {}
        for cap in caps_rows:
            settlement_map[(cap.exchange, cap.symbol)] = cap.interval_hours

        # Group by (exchange, coin)
        grouped: dict[tuple[str, str], list[dict[str, float]]] = defaultdict(list)
        for r in all_records:
            grouped[(r.exchange, r.coin)].append(
                {"time_ms": self._dt_to_ms(r.funding_time), "rate": r.funding_rate}
            )

        # Coins per exchange
        exchange_coins: dict[str, set[str]] = defaultdict(set)
        for ex, coin in grouped:
            exchange_coins[ex].add(coin)

        results: list[dict] = []
        for long_ex, short_ex in BOARDS:
            common_coins = exchange_coins.get(long_ex, set()) & exchange_coins.get(short_ex, set())
            if not common_coins:
                continue

            for coin in common_coins:
                long_records = grouped.get((long_ex, coin), [])
                short_records = grouped.get((short_ex, coin), [])

                if not long_records and not short_records:
                    continue

                long_total, long_count = self._calculate_funding_for_side(long_records, "long")
                short_total, short_count = self._calculate_funding_for_side(short_records, "short")
                total_diff = long_total + short_total

                # Settlement periods
                long_caps_ex = self._CAPS_EXCHANGE_MAP.get(long_ex, long_ex)
                short_caps_ex = self._CAPS_EXCHANGE_MAP.get(short_ex, short_ex)
                long_period = settlement_map.get((long_caps_ex, coin), 8)
                short_period = settlement_map.get((short_caps_ex, coin), 8)

                results.append({
                    "coin": coin,
                    "long_exchange": long_ex,
                    "short_exchange": short_ex,
                    "long_total_funding": round(long_total * 100, 3),
                    "short_total_funding": round(short_total * 100, 3),
                    "long_settlement_count": long_count,
                    "short_settlement_count": short_count,
                    "long_settlement_period": long_period,
                    "short_settlement_period": short_period,
                    "total_diff": round(total_diff * 100, 3),
                })

        # Sort by total_diff descending
        results.sort(key=lambda x: x["total_diff"], reverse=True)
        return results

    async def get_funding_detail(
        self, coin: str, long_exchange: str, short_exchange: str,
        start_time: int, end_time: int
    ) -> list[dict]:
        """Get per-period funding rate detail from DB."""
        start_dt = self._ms_to_dt(start_time)
        end_dt = self._ms_to_dt(end_time)

        async with async_session_factory() as db:
            long_result = await db.execute(
                select(FundingHistory)
                .where(FundingHistory.exchange == long_exchange)
                .where(FundingHistory.coin == coin)
                .where(FundingHistory.funding_time >= start_dt)
                .where(FundingHistory.funding_time <= end_dt)
            )
            short_result = await db.execute(
                select(FundingHistory)
                .where(FundingHistory.exchange == short_exchange)
                .where(FundingHistory.coin == coin)
                .where(FundingHistory.funding_time >= start_dt)
                .where(FundingHistory.funding_time <= end_dt)
            )
            long_map = {self._dt_to_ms(r.funding_time): r.funding_rate for r in long_result.scalars().all()}
            short_map = {self._dt_to_ms(r.funding_time): r.funding_rate for r in short_result.scalars().all()}

        all_times = sorted(set(long_map.keys()) | set(short_map.keys()), reverse=True)

        details = []
        for t in all_times:
            long_rate = long_map.get(t)
            short_rate = short_map.get(t)
            long_funding = round(-long_rate * 100, 3) if long_rate is not None else None
            short_funding = round(short_rate * 100, 3) if short_rate is not None else None
            diff = round((((-long_rate) if long_rate is not None else 0.0) +
                          (short_rate if short_rate is not None else 0.0)) * 100, 3)
            dt = datetime.fromtimestamp(t / 1000, tz=_UTC8)
            details.append({
                "time": t,
                "time_str": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "long_funding": long_funding,
                "short_funding": short_funding,
                "diff": diff,
            })

        return details

    async def calculate_statistics(
        self, coin: str, long_exchange: str, short_exchange: str,
        start_time: int, end_time: int
    ) -> dict:
        """Funding calculator tool - reads from DB (single long exchange)."""
        return await self.calculate_statistics_multi(
            coin, long_exchange, short_exchange, start_time, end_time
        )

    async def _get_funding_map(
        self, coin: str, exchange: str, start_dt: datetime, end_dt: datetime
    ) -> dict[int, float]:
        """Get {time_ms: rate} for one exchange+coin from DB."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(FundingHistory)
                .where(FundingHistory.exchange == exchange)
                .where(FundingHistory.coin == coin)
                .where(FundingHistory.funding_time >= start_dt)
                .where(FundingHistory.funding_time <= end_dt)
            )
            return {self._dt_to_ms(r.funding_time): r.funding_rate for r in result.scalars().all()}

    async def calculate_statistics_multi(
        self, coin: str, long_exchange: str, short_exchange: str,
        start_time: int, end_time: int,
        long_exchange2: Optional[str] = None,
    ) -> dict:
        """Funding calculator with optional second long exchange."""
        start_dt = self._ms_to_dt(start_time)
        end_dt = self._ms_to_dt(end_time)

        long1_map = await self._get_funding_map(coin, long_exchange, start_dt, end_dt)
        short_map = await self._get_funding_map(coin, short_exchange, start_dt, end_dt)
        long2_map = await self._get_funding_map(coin, long_exchange2, start_dt, end_dt) if long_exchange2 else {}

        has_long2 = bool(long_exchange2 and long2_map)
        all_times = sorted(set(long1_map.keys()) | set(short_map.keys()) | set(long2_map.keys()), reverse=True)

        # Per-period details
        per_period = []
        for t in all_times:
            l1 = long1_map.get(t)
            l2 = long2_map.get(t) if has_long2 else None
            s = short_map.get(t)
            long1_val = round(-l1 * 100, 3) if l1 is not None else None
            long2_val = round(-l2 * 100, 3) if l2 is not None else None
            short_val = round(s * 100, 3) if s is not None else None
            diff1 = round((((-l1) if l1 is not None else 0) + (s if s is not None else 0)) * 100, 3)
            diff2 = round((((-l2) if l2 is not None else 0) + (s if s is not None else 0)) * 100, 3) if has_long2 else None

            dt = datetime.fromtimestamp(t / 1000, tz=_UTC8)
            item: dict = {
                "time": t,
                "time_str": dt.strftime("%Y-%m-%d %H:%M:%S"),
                "long1_funding": long1_val,
                "short_funding": short_val,
                "diff1": diff1,
            }
            if has_long2:
                item["long2_funding"] = long2_val
                item["diff2"] = diff2
            per_period.append(item)

        # Per-day summary
        daily: dict[str, dict[str, float]] = defaultdict(
            lambda: {"long1": 0.0, "long2": 0.0, "short": 0.0, "diff1": 0.0, "diff2": 0.0}
        )
        for item in per_period:
            dt = datetime.fromtimestamp(item["time"] / 1000, tz=_UTC8)
            date_str = dt.strftime("%Y-%m-%d")
            daily[date_str]["long1"] += item["long1_funding"] or 0.0
            daily[date_str]["short"] += item["short_funding"] or 0.0
            daily[date_str]["diff1"] += item["diff1"] or 0.0
            if has_long2:
                daily[date_str]["long2"] += item.get("long2_funding") or 0.0
                daily[date_str]["diff2"] += item.get("diff2") or 0.0

        per_day = []
        for date_str in sorted(daily.keys()):
            d = daily[date_str]
            row: dict = {
                "date": date_str,
                "long1_total": round(d["long1"], 3),
                "short_total": round(d["short"], 3),
                "diff1": round(d["diff1"], 3),
            }
            if has_long2:
                row["long2_total"] = round(d["long2"], 3)
                row["diff2"] = round(d["diff2"], 3)
            per_day.append(row)

        # Summary
        summary: dict = {
            "long1_total": round(sum(item["long1_funding"] or 0.0 for item in per_period), 3),
            "short_total": round(sum(item["short_funding"] or 0.0 for item in per_period), 3),
            "diff1": round(sum(item["diff1"] or 0.0 for item in per_period), 3),
        }
        if has_long2:
            summary["long2_total"] = round(sum(item.get("long2_funding") or 0.0 for item in per_period), 3)
            summary["diff2"] = round(sum(item.get("diff2") or 0.0 for item in per_period), 3)

        return {
            "per_period": per_period,
            "per_day": per_day,
            "summary": summary,
            "long_exchange": long_exchange,
            "short_exchange": short_exchange,
            "long_exchange2": long_exchange2 if has_long2 else None,
        }
