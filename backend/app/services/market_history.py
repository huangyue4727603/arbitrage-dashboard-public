"""Fetch /api/v1/arbitrage/chance/histories and persist to arb_market_history.

API returns: {code, msg, data: [ {seqId, exchange, coin, symbol, instId,
instType, price, fundingRate, premium, openInterest, fundingInterval,
baseVol24h, quoteVol24h, createdAt}, ... ]}

`createdAt` is a millisecond epoch.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import aiohttp
from sqlalchemy import select, func
from sqlalchemy.dialects.mysql import insert as mysql_insert

from app.config import get_settings
from app.database import async_session_factory
from app.models.market_data import MarketHistory

logger = logging.getLogger(__name__)


def _to_dec(v: Any) -> Optional[Decimal]:
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError):
        return None


def _to_int(v: Any) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


async def fetch_histories(ts_ms: int) -> list[dict]:
    """GET /api/v1/arbitrage/chance/histories?ts=...&exchangeEnums=BINANCE,OKX,BYBIT"""
    base = get_settings().ARBITRAGE_API_URL.rstrip("/")
    url = f"{base}/crossapi/v1/arbitrage/chance/histories"
    params = {"ts": ts_ms, "exchangeEnums": "BINANCE,OKX,BYBIT"}
    timeout = aiohttp.ClientTimeout(total=600, sock_connect=30, sock_read=300)
    # trust_env=False — arbitrage API is direct (same as data_fetcher)
    async with aiohttp.ClientSession(trust_env=False, timeout=timeout) as s:
        async with s.get(url, params=params) as r:
            r.raise_for_status()
            body = await r.json()
    if not isinstance(body, dict) or body.get("code") not in (0, "0", 200):
        logger.warning("market_history API returned non-success: code=%s msg=%s", body.get("code"), body.get("msg"))
    data = body.get("data") if isinstance(body, dict) else None
    return data if isinstance(data, list) else []


async def get_max_created_at_ms() -> Optional[int]:
    """Return latest stored row's created_at as ms epoch."""
    async with async_session_factory() as db:
        r = await db.execute(select(func.max(MarketHistory.created_at)))
        v = r.scalar()
    if v is None:
        return None
    return int(v.timestamp() * 1000)


async def insert_rows(rows: list[dict]) -> int:
    """Bulk insert with INSERT IGNORE on seq_id unique. Returns inserted count."""
    if not rows:
        return 0
    payload = []
    for r in rows:
        seq = _to_int(r.get("seqId"))
        created_ms = _to_int(r.get("createdAt"))
        if seq is None or created_ms is None:
            continue
        payload.append({
            "seq_id": seq,
            "exchange": str(r.get("exchange") or "")[:20],
            "coin": str(r.get("coin") or "")[:50],
            "symbol": str(r.get("symbol") or "")[:80],
            "inst_id": str(r.get("instId") or "")[:80],
            "inst_type": str(r.get("instType") or "")[:20],
            "price": _to_dec(r.get("price")),
            "funding_rate": _to_dec(r.get("fundingRate")),
            "premium": _to_dec(r.get("premium")),
            "open_interest": _to_dec(r.get("openInterest")),
            "funding_interval": _to_int(r.get("fundingInterval")),
            "base_vol24h": _to_dec(r.get("baseVol24h")),
            "quote_vol24h": _to_dec(r.get("quoteVol24h")),
            "created_at": datetime.fromtimestamp(created_ms / 1000),
        })
    if not payload:
        return 0
    inserted = 0
    async with async_session_factory() as db:
        # Chunk to avoid massive single statement
        CHUNK = 1000
        for i in range(0, len(payload), CHUNK):
            chunk = payload[i:i + CHUNK]
            stmt = mysql_insert(MarketHistory).values(chunk).prefix_with("IGNORE")
            res = await db.execute(stmt)
            inserted += res.rowcount or 0
        await db.commit()
    return inserted


async def cleanup_old(days: int = 3) -> int:
    """Delete rows older than `days` days. Returns deleted rowcount."""
    from sqlalchemy import delete
    cutoff = datetime.now()
    from datetime import timedelta
    cutoff = cutoff - timedelta(days=days)
    async with async_session_factory() as db:
        res = await db.execute(delete(MarketHistory).where(MarketHistory.created_at < cutoff))
        await db.commit()
        return res.rowcount or 0
