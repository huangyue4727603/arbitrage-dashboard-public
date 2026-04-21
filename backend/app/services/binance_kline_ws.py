"""Binance Futures WebSocket kline subscriber.

Subscribes to kline streams for all USDT perpetual symbols across all intervals.
On candle close (k.x == true), upserts into arb_price_klines table.

Replaces REST-based kline polling to avoid IP bans.

Binance Futures WS docs:
- URL: wss://fstream.binance.com/ws (single) or /stream (combined)
- Subscribe via message: {"method": "SUBSCRIBE", "params": [...], "id": N}
- Max ~200 streams per connection
- Kline stream name: <symbol_lower>@kline_<interval>
- Kline event: k.x == true means candle is closed/final
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any, Optional

import aiohttp
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.config import get_proxy
from app.database import async_session_factory
from app.models.market_data import PriceKline

logger = logging.getLogger(__name__)

# Binance limits
MAX_STREAMS_PER_CONN = 200
SUBSCRIBE_BATCH_SIZE = 50  # subscribe in smaller batches to avoid timeouts

KLINE_INTERVALS = ["5m", "15m", "1h", "4h", "1d"]

# Reconnect settings
RECONNECT_DELAY_BASE = 5    # seconds
RECONNECT_DELAY_MAX = 120   # seconds
PING_INTERVAL = 180         # seconds (Binance disconnects after 5min silence)


class _WSConnection:
    """Manages a single WebSocket connection with up to MAX_STREAMS_PER_CONN streams."""

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
        """Reconnection loop."""
        while self._running:
            try:
                await self._connect_and_listen()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._running:
                    break
                logger.warning("WS conn #%d error: %s, reconnecting in %ds",
                               self.conn_id, exc, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, RECONNECT_DELAY_MAX)

    async def _connect_and_listen(self):
        proxy = get_proxy() or None
        timeout = aiohttp.ClientTimeout(total=30, sock_connect=10)

        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=timeout)

        url = "wss://fstream.binance.com/ws"
        logger.info("WS conn #%d connecting (%d streams)...", self.conn_id, len(self.streams))

        async with self._session.ws_connect(url, proxy=proxy, heartbeat=PING_INTERVAL) as ws:
            self._ws = ws
            self._reconnect_delay = RECONNECT_DELAY_BASE  # reset on successful connect

            # Subscribe in batches
            for i in range(0, len(self.streams), SUBSCRIBE_BATCH_SIZE):
                batch = self.streams[i:i + SUBSCRIBE_BATCH_SIZE]
                msg = {"method": "SUBSCRIBE", "params": batch, "id": i + 1}
                await ws.send_json(msg)
                await asyncio.sleep(0.5)  # small delay between subscribe batches

            logger.info("WS conn #%d subscribed to %d streams", self.conn_id, len(self.streams))

            async for raw_msg in ws:
                if raw_msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(raw_msg.data)
                        await self._handle_message(data)
                    except json.JSONDecodeError:
                        pass
                elif raw_msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning("WS conn #%d closed/error", self.conn_id)
                    break

    async def _handle_message(self, data: dict[str, Any]):
        """Process a kline WebSocket message."""
        # Subscribe response — ignore
        if "result" in data or "id" in data:
            return

        # Stream wrapper: {"stream": "...", "data": {...}}
        if "stream" in data:
            data = data.get("data", data)

        event_type = data.get("e")
        if event_type != "kline":
            return

        k = data.get("k", {})
        is_closed = k.get("x", False)

        if not is_closed:
            return  # Only store finalized candles

        symbol = k.get("s", "")       # e.g. "BTCUSDT"
        interval = k.get("i", "")     # e.g. "5m"
        open_time = k.get("t", 0)     # open time in ms

        if not symbol or not interval or not open_time:
            return

        kline_time = datetime.fromtimestamp(open_time / 1000)

        await self.on_kline_close(
            symbol=symbol,
            interval=interval,
            kline_time=kline_time,
            open_price=float(k.get("o", 0)),
            high_price=float(k.get("h", 0)),
            low_price=float(k.get("l", 0)),
            close_price=float(k.get("c", 0)),
        )


class BinanceKlineWS:
    """Manages multiple WebSocket connections to cover all symbol×interval streams."""

    def __init__(self) -> None:
        self._connections: list[_WSConnection] = []
        self._running = False
        self._symbols: list[str] = []
        self._write_queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: Optional[asyncio.Task] = None
        # Stats
        self._total_stored = 0
        self._last_log_time = 0.0

    async def start(self, symbols: list[str]) -> None:
        """Start WebSocket subscriptions for all symbols × intervals."""
        if self._running:
            return

        self._symbols = symbols
        self._running = True

        # Build all stream names
        all_streams: list[str] = []
        for symbol in symbols:
            sym_lower = symbol.lower()
            for interval in KLINE_INTERVALS:
                all_streams.append(f"{sym_lower}@kline_{interval}")

        logger.info("Kline WS: %d symbols × %d intervals = %d streams",
                     len(symbols), len(KLINE_INTERVALS), len(all_streams))

        # Split into connections of MAX_STREAMS_PER_CONN each
        for i in range(0, len(all_streams), MAX_STREAMS_PER_CONN):
            chunk = all_streams[i:i + MAX_STREAMS_PER_CONN]
            conn = _WSConnection(
                conn_id=i // MAX_STREAMS_PER_CONN,
                streams=chunk,
                on_kline_close=self._enqueue_kline,
            )
            self._connections.append(conn)

        logger.info("Kline WS: starting %d connections", len(self._connections))

        # Start DB writer task
        self._writer_task = asyncio.create_task(self._db_writer())

        # Start all connections
        for conn in self._connections:
            await conn.start()
            await asyncio.sleep(1)  # stagger connection starts

    async def stop(self) -> None:
        """Stop all WebSocket connections."""
        self._running = False
        for conn in self._connections:
            await conn.stop()
        self._connections.clear()

        if self._writer_task:
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass

        logger.info("Kline WS stopped (total stored: %d)", self._total_stored)

    async def _enqueue_kline(self, **kline_data):
        """Enqueue a closed kline for batch DB write."""
        await self._write_queue.put(kline_data)

    async def _db_writer(self):
        """Batch writer: collects klines from queue and writes to DB periodically."""
        while self._running:
            try:
                batch: list[dict[str, Any]] = []

                # Wait for at least one item
                try:
                    item = await asyncio.wait_for(self._write_queue.get(), timeout=5.0)
                    batch.append(item)
                except asyncio.TimeoutError:
                    continue

                # Drain queue (non-blocking) for batch efficiency
                while not self._write_queue.empty() and len(batch) < 500:
                    try:
                        batch.append(self._write_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                if batch:
                    await self._write_batch(batch)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Kline WS DB writer error: %s", exc)
                await asyncio.sleep(1)

    async def _write_batch(self, batch: list[dict[str, Any]]):
        """Write a batch of klines to DB using bulk insert."""
        try:
            values = [
                {
                    "symbol": k["symbol"],
                    "interval_type": k["interval"],
                    "open_price": k["open_price"],
                    "high_price": k["high_price"],
                    "low_price": k["low_price"],
                    "close_price": k["close_price"],
                    "kline_time": k["kline_time"],
                }
                for k in batch
            ]
            async with async_session_factory() as db:
                stmt = mysql_insert(PriceKline).values(values)
                stmt = stmt.on_duplicate_key_update(
                    open_price=stmt.inserted.open_price,
                    high_price=stmt.inserted.high_price,
                    low_price=stmt.inserted.low_price,
                    close_price=stmt.inserted.close_price,
                )
                await db.execute(stmt)
                await db.commit()

            self._total_stored += len(batch)

            # Log stats every 60 seconds
            now = time.time()
            if now - self._last_log_time > 60:
                self._last_log_time = now
                logger.info("Kline WS: stored %d candles (batch=%d, queue=%d)",
                            self._total_stored, len(batch), self._write_queue.qsize())
        except Exception as exc:
            logger.error("Kline WS batch write failed (%d items): %s", len(batch), exc)

    def get_symbols(self) -> list[str]:
        return self._symbols


# Module-level singleton
binance_kline_ws = BinanceKlineWS()
