"""Bybit WebSocket kline subscriber.

Subscribes to kline.D for all USDT linear perpetual symbols.
Caches kline data in memory for new_listing detection.

Bybit Public WS: wss://stream.bybit.com/v5/public/linear
- Subscribe: {"op": "subscribe", "args": ["kline.D.BTCUSDT"]}
- Data: confirm=true means candle is closed
- Keep-alive: server sends {"op": "ping"}, client responds {"op": "pong"}
- Max 200 subscriptions per connection
"""
import asyncio
import json
import logging
import time
from collections import defaultdict
from typing import Any, Optional

import aiohttp

from app.config import get_proxy

logger = logging.getLogger(__name__)

WS_URL = "wss://stream.bybit.com/v5/public/linear"
MAX_STREAMS_PER_CONN = 200
SUBSCRIBE_BATCH_SIZE = 50
MAX_KLINES_PER_SYMBOL = 100
RECONNECT_DELAY_BASE = 5
RECONNECT_DELAY_MAX = 120
PING_INTERVAL = 20


class _BybitWSConn:
    """Single Bybit WebSocket connection handling up to 200 streams."""

    def __init__(self, conn_id: int, streams: list[str], on_kline_close):
        self.conn_id = conn_id
        self.streams = streams
        self.on_kline_close = on_kline_close
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._reconnect_delay = RECONNECT_DELAY_BASE

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self):
        self._running = False
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

    async def _run_loop(self):
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("Bybit WS conn #%d error: %s, reconnecting in %ds",
                               self.conn_id, exc, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, RECONNECT_DELAY_MAX)

    async def _connect_and_listen(self):
        proxy = get_proxy() or None
        timeout = aiohttp.ClientTimeout(total=30, sock_connect=10)

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=timeout)

        logger.info("Bybit WS conn #%d connecting (%d streams)...", self.conn_id, len(self.streams))

        async with self._session.ws_connect(WS_URL, proxy=proxy, heartbeat=PING_INTERVAL) as ws:
            self._ws = ws
            self._reconnect_delay = RECONNECT_DELAY_BASE

            # Subscribe in batches
            for i in range(0, len(self.streams), SUBSCRIBE_BATCH_SIZE):
                batch = self.streams[i:i + SUBSCRIBE_BATCH_SIZE]
                await ws.send_json({"op": "subscribe", "args": batch})
                await asyncio.sleep(0.5)

            logger.info("Bybit WS conn #%d subscribed to %d streams", self.conn_id, len(self.streams))

            async for raw_msg in ws:
                if raw_msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(raw_msg.data)
                        # Respond to server ping
                        if data.get("op") == "ping":
                            await ws.send_json({"op": "pong"})
                            continue
                        # Skip subscribe confirmations
                        if "success" in data:
                            continue
                        self._handle_message(data)
                    except json.JSONDecodeError:
                        pass
                elif raw_msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break

    def _handle_message(self, data: dict[str, Any]):
        topic = data.get("topic", "")
        if not topic.startswith("kline."):
            return

        # topic format: "kline.D.BTCUSDT"
        parts = topic.split(".")
        if len(parts) < 3:
            return
        symbol = parts[2]

        for candle in data.get("data", []):
            if not candle.get("confirm", False):
                continue  # Only closed candles

            ts = int(candle.get("start", 0))
            o = float(candle.get("open", 0))
            h = float(candle.get("high", 0))
            l = float(candle.get("low", 0))
            c = float(candle.get("close", 0))

            self.on_kline_close(symbol, ts, o, h, l, c)


class BybitKlineWS:
    """Manages Bybit WebSocket connections for 1D kline data."""

    def __init__(self) -> None:
        self._connections: list[_BybitWSConn] = []
        self._running = False
        self._symbols: list[str] = []
        # Cache: symbol -> list of (kline_time_ms, o, h, l, c)
        self._kline_cache: dict[str, list[tuple[int, float, float, float, float]]] = defaultdict(list)
        self._total_received = 0
        self._last_log_time = 0.0

    async def start(self, symbols: list[str]) -> None:
        if self._running:
            return
        self._symbols = symbols
        self._running = True

        # Build stream names
        streams = [f"kline.D.{s}" for s in symbols]
        logger.info("Bybit kline WS: %d symbols", len(symbols))

        # Split into connections
        for i in range(0, len(streams), MAX_STREAMS_PER_CONN):
            chunk = streams[i:i + MAX_STREAMS_PER_CONN]
            conn = _BybitWSConn(
                conn_id=i // MAX_STREAMS_PER_CONN,
                streams=chunk,
                on_kline_close=self._on_kline_close,
            )
            self._connections.append(conn)

        logger.info("Bybit kline WS: starting %d connections", len(self._connections))

        for conn in self._connections:
            await conn.start()
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        for conn in self._connections:
            await conn.stop()
        self._connections.clear()
        logger.info("Bybit kline WS stopped (received: %d)", self._total_received)

    def _on_kline_close(self, symbol: str, ts: int, o: float, h: float, l: float, c: float):
        klines = self._kline_cache[symbol]
        if not klines or klines[-1][0] != ts:
            klines.append((ts, o, h, l, c))
            if len(klines) > MAX_KLINES_PER_SYMBOL:
                self._kline_cache[symbol] = klines[-MAX_KLINES_PER_SYMBOL:]

        self._total_received += 1

        now = time.time()
        if now - self._last_log_time > 60:
            self._last_log_time = now
            logger.info("Bybit kline WS: received %d candles, tracking %d symbols",
                        self._total_received, len(self._kline_cache))

    def get_kline_count(self, symbol: str) -> int:
        return len(self._kline_cache.get(symbol, []))

    def get_first_kline(self, symbol: str) -> Optional[tuple[int, float, float, float, float]]:
        klines = self._kline_cache.get(symbol)
        if klines:
            return klines[0]
        return None

    def get_cached_symbols(self) -> set[str]:
        return set(self._kline_cache.keys())


# Module-level singleton
bybit_kline_ws = BybitKlineWS()
