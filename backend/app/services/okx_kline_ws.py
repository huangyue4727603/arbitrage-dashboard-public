"""OKX WebSocket kline subscriber.

Subscribes to candle1D for all USDT-SWAP instruments.
Caches kline data in memory for new_listing detection.

OKX Business WS: wss://ws.okx.com:8443/ws/v5/business
- Subscribe: {"op": "subscribe", "args": [{"channel": "candle1D", "instId": "BTC-USDT-SWAP"}]}
- Data: confirm="1" means candle is closed
- Keep-alive: send "ping" text every 25s
"""
import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime
from typing import Any, Optional

import aiohttp

from app.config import get_proxy

logger = logging.getLogger(__name__)

WS_URL = "wss://ws.okx.com:8443/ws/v5/business"
SUBSCRIBE_BATCH_SIZE = 50
MAX_KLINES_PER_SYMBOL = 100  # keep at most 100 1d klines in memory
RECONNECT_DELAY_BASE = 5
RECONNECT_DELAY_MAX = 120
PING_INTERVAL = 25  # OKX requires ping every 30s, use 25s to be safe


class OKXKlineWS:
    """WebSocket subscriber for OKX 1D kline data."""

    def __init__(self) -> None:
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None
        self._running = False
        self._inst_ids: list[str] = []
        self._reconnect_delay = RECONNECT_DELAY_BASE
        # Cache: inst_id -> list of (kline_time_ms, open, high, low, close)
        self._kline_cache: dict[str, list[tuple[int, float, float, float, float]]] = defaultdict(list)
        self._total_received = 0
        self._last_log_time = 0.0

    async def start(self, inst_ids: list[str]) -> None:
        if self._running:
            return
        self._inst_ids = inst_ids
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("OKX kline WS: starting for %d instruments", len(inst_ids))

    async def stop(self) -> None:
        self._running = False
        if self._ping_task:
            self._ping_task.cancel()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("OKX kline WS stopped (received: %d)", self._total_received)

    def get_kline_count(self, inst_id: str) -> int:
        """Return number of cached 1D klines for a given instrument."""
        return len(self._kline_cache.get(inst_id, []))

    def get_first_kline(self, inst_id: str) -> Optional[tuple[int, float, float, float, float]]:
        """Return the oldest cached 1D kline (kline_time_ms, o, h, l, c)."""
        klines = self._kline_cache.get(inst_id)
        if klines:
            return klines[0]
        return None

    def get_cached_symbols(self) -> set[str]:
        """Return set of inst_ids that have cached kline data."""
        return set(self._kline_cache.keys())

    async def _run_loop(self):
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("OKX kline WS error: %s, reconnecting in %ds",
                               exc, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, RECONNECT_DELAY_MAX)

    async def _connect_and_listen(self):
        proxy = get_proxy() or None
        timeout = aiohttp.ClientTimeout(total=30, sock_connect=10)

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=timeout)

        logger.info("OKX kline WS connecting (%d instruments)...", len(self._inst_ids))

        async with self._session.ws_connect(WS_URL, proxy=proxy) as ws:
            self._ws = ws
            self._reconnect_delay = RECONNECT_DELAY_BASE

            # Start ping task
            self._ping_task = asyncio.create_task(self._ping_loop(ws))

            # Subscribe in batches
            for i in range(0, len(self._inst_ids), SUBSCRIBE_BATCH_SIZE):
                batch = self._inst_ids[i:i + SUBSCRIBE_BATCH_SIZE]
                args = [{"channel": "candle1D", "instId": iid} for iid in batch]
                await ws.send_json({"op": "subscribe", "args": args})
                await asyncio.sleep(0.5)

            logger.info("OKX kline WS subscribed to %d instruments", len(self._inst_ids))

            async for raw_msg in ws:
                if raw_msg.type == aiohttp.WSMsgType.TEXT:
                    text = raw_msg.data
                    if text == "pong":
                        continue
                    try:
                        data = json.loads(text)
                        self._handle_message(data)
                    except json.JSONDecodeError:
                        pass
                elif raw_msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

            if self._ping_task:
                self._ping_task.cancel()

    async def _ping_loop(self, ws: aiohttp.ClientWebSocketResponse):
        try:
            while self._running and not ws.closed:
                await ws.send_str("ping")
                await asyncio.sleep(PING_INTERVAL)
        except (asyncio.CancelledError, ConnectionError):
            pass

    def _handle_message(self, data: dict[str, Any]):
        # Subscribe confirmation
        if data.get("event") == "subscribe":
            return

        arg = data.get("arg", {})
        channel = arg.get("channel", "")
        if not channel.startswith("candle"):
            return

        inst_id = arg.get("instId", "")
        if not inst_id:
            return

        for candle in data.get("data", []):
            # candle format: [ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]
            if len(candle) < 9:
                continue
            confirm = candle[8]
            if confirm != "1":
                continue  # Only store closed candles

            ts = int(candle[0])
            o = float(candle[1])
            h = float(candle[2])
            l = float(candle[3])
            c = float(candle[4])

            klines = self._kline_cache[inst_id]
            # Avoid duplicates
            if not klines or klines[-1][0] != ts:
                klines.append((ts, o, h, l, c))
                # Trim to max
                if len(klines) > MAX_KLINES_PER_SYMBOL:
                    self._kline_cache[inst_id] = klines[-MAX_KLINES_PER_SYMBOL:]

            self._total_received += 1

            now = time.time()
            if now - self._last_log_time > 60:
                self._last_log_time = now
                logger.info("OKX kline WS: received %d candles, tracking %d instruments",
                            self._total_received, len(self._kline_cache))


# Module-level singleton
okx_kline_ws = OKXKlineWS()
