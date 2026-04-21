"""Rolling scheduler that keeps arb_index_constituents fresh.

- Two independent async tasks: one for "fast" exchanges (BN+OKX), one for "slow" (Bybit/Playwright).
- Each task rotates through the full coin list at a configurable per-coin sleep,
  so the throughput is naturally rate-limited (no thundering-herd at xx:00).
- A high-priority queue handles new coins (first-time fetches) — they jump the line.
- Coins are sourced from arb_funding_history (distinct coin column) once per cycle.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import distinct, select, delete

from app.database import async_session_factory
from app.models.market_data import FundingHistory, IndexConstituent
from app.services.index_constituents import (
    FETCHERS,
    fetch_binance,
    fetch_okx,
    fetch_bybit,
)

logger = logging.getLogger(__name__)

# Per-tick: fetch BATCH coins in parallel, then sleep BATCH_SLEEP_SEC.
# Throughput = BATCH / BATCH_SLEEP_SEC coins/sec per worker.
BATCH = 5
BATCH_SLEEP_SEC = 10      # 5 coins per 10s per worker → 0.5 coins/s (avoid Binance rate limit)
SLOW_SLEEP_SEC = 15       # Bybit Playwright (per coin, single-threaded)

# How often to refresh the in-memory coin list from DB
COIN_REFRESH_SEC = 600


class IndexConstituentsScheduler:
    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._stopped = False
        self._coin_list: list[str] = []
        self._coin_set: set[str] = set()
        self._last_coin_refresh: float = 0
        # Priority queue for new coins (first-time)
        self._priority_q: asyncio.Queue[str] = asyncio.Queue()
        self._priority_set: set[str] = set()

    # ---------------- coin list ----------------
    async def _refresh_coin_list(self) -> None:
        async with async_session_factory() as db:
            r = await db.execute(select(distinct(FundingHistory.coin)).order_by(FundingHistory.coin))
            coins = [row[0] for row in r.all() if row[0]]
        self._coin_list = coins
        self._coin_set = set(coins)
        self._last_coin_refresh = asyncio.get_event_loop().time()
        logger.info("index-constituents: coin list = %d coins", len(coins))

    async def _ensure_coin_list(self) -> None:
        loop = asyncio.get_event_loop()
        if not self._coin_list or (loop.time() - self._last_coin_refresh) > COIN_REFRESH_SEC:
            await self._refresh_coin_list()

    # ---------------- known coins (already in constituents table) ----------------
    async def _existing_coins_for(self, exchange: str) -> set[str]:
        async with async_session_factory() as db:
            r = await db.execute(
                select(IndexConstituent.coin).where(IndexConstituent.exchange == exchange)
            )
            return {row[0] for row in r.all()}

    # ---------------- new coin trigger ----------------
    async def queue_new_coins(self, coins: list[str]) -> None:
        """Public API: enqueue coins for high-priority fetching (e.g., from funding_rank)."""
        for c in coins:
            if c and c not in self._priority_set:
                self._priority_set.add(c)
                await self._priority_q.put(c)

    async def _detect_and_queue_new(self) -> None:
        """Compare coin list against arb_index_constituents and queue first-timers."""
        await self._ensure_coin_list()
        # Use BN as the canonical "have we ever fetched" check
        existing = await self._existing_coins_for("BN")
        new_coins = [c for c in self._coin_list if c not in existing]
        if new_coins:
            logger.info("index-constituents: queueing %d new coins for priority fetch", len(new_coins))
            await self.queue_new_coins(new_coins)

    # ---------------- DB upsert (delete-and-insert per coin+exchange) ----------------
    async def _upsert(self, coin: str, exchange: str, constituents: list[dict]) -> None:
        if not constituents:
            return
        now = datetime.now()
        async with async_session_factory() as db:
            # Delete existing rows for this (coin, exchange) — composition can change
            await db.execute(
                delete(IndexConstituent)
                .where(IndexConstituent.coin == coin)
                .where(IndexConstituent.exchange == exchange)
            )
            for c in constituents:
                exch = (c.get("exch") or "").strip()
                if not exch:
                    continue
                try:
                    weight = float(c.get("weight") or 0)
                except (TypeError, ValueError):
                    continue
                if weight <= 0:
                    continue
                db.add(IndexConstituent(
                    coin=coin,
                    exchange=exchange,
                    spot_exchange=exch,
                    spot_symbol=str(c.get("symbol") or ""),
                    weight=weight,
                    fetched_at=now,
                ))
            await db.commit()

    # ---------------- worker loops ----------------
    async def _drain_priority(self, n: int) -> list[str]:
        out: list[str] = []
        while len(out) < n and not self._priority_q.empty():
            try:
                out.append(self._priority_q.get_nowait())
            except asyncio.QueueEmpty:
                break
        return out

    async def _exchange_loop(self, exchange: str, fetcher) -> None:
        """Generic batch fetcher: BATCH coins in parallel, then sleep."""
        idx = 0
        while not self._stopped:
            try:
                await self._ensure_coin_list()
                if not self._coin_list:
                    await asyncio.sleep(5)
                    continue

                # Priority first
                batch = await self._drain_priority(BATCH)
                if len(batch) < BATCH:
                    n = len(self._coin_list)
                    for _ in range(BATCH - len(batch)):
                        batch.append(self._coin_list[idx % n])
                        idx += 1

                results = await asyncio.gather(*(fetcher(c) for c in batch), return_exceptions=True)
                ok = 0
                rate_limited = False
                for c, r in zip(batch, results):
                    if isinstance(r, list) and r:
                        await self._upsert(c, exchange, r)
                        ok += 1
                    elif isinstance(r, Exception) and "418" in str(r):
                        rate_limited = True
                logger.info("[%s] batch=%d ok=%d", exchange, len(batch), ok)

                if rate_limited or (ok == 0 and len(batch) > 2):
                    logger.warning("[%s] Rate limited or all failed, pausing 5 minutes", exchange)
                    await asyncio.sleep(300)
                else:
                    await asyncio.sleep(BATCH_SLEEP_SEC)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("%s loop error: %s", exchange, exc)
                await asyncio.sleep(10)

    async def _slow_loop(self) -> None:
        """Bybit Playwright fetcher (slow)."""
        idx = 0
        while not self._stopped:
            try:
                await self._ensure_coin_list()
                if not self._coin_list:
                    await asyncio.sleep(10)
                    continue

                coin = self._coin_list[idx % len(self._coin_list)]
                idx += 1
                data = await fetch_bybit(coin)
                if data is not None:
                    await self._upsert(coin, "BY", data)

                await asyncio.sleep(SLOW_SLEEP_SEC)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("slow_loop error: %s", exc)
                await asyncio.sleep(30)

    async def _new_coin_detector_loop(self) -> None:
        """Periodically check for new coins to enqueue."""
        # Initial detection right after start
        await asyncio.sleep(5)
        while not self._stopped:
            try:
                await self._detect_and_queue_new()
            except Exception as exc:
                logger.error("new_coin_detector error: %s", exc)
            await asyncio.sleep(300)  # every 5min

    # ---------------- lifecycle ----------------
    def start(self) -> None:
        if self._tasks:
            return
        self._stopped = False
        loop = asyncio.get_event_loop()
        import os
        self._tasks = [
            loop.create_task(self._exchange_loop("BN", fetch_binance), name="idx_const_bn"),
            loop.create_task(self._exchange_loop("OKX", fetch_okx), name="idx_const_okx"),
            loop.create_task(self._exchange_loop("BY", fetch_bybit), name="idx_const_by"),
            loop.create_task(self._new_coin_detector_loop(), name="idx_const_detect"),
        ]
        logger.info(
            "index_constituents_scheduler started (batch=%d/%ds per worker, slow=%ds)",
            BATCH, BATCH_SLEEP_SEC, SLOW_SLEEP_SEC,
        )

    def stop(self) -> None:
        self._stopped = True
        for t in self._tasks:
            if not t.done():
                t.cancel()
        self._tasks = []
        logger.info("index_constituents_scheduler stopped")


index_constituents_scheduler = IndexConstituentsScheduler()
