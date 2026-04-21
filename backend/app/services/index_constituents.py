"""Fetch and normalize index price constituents across exchanges.

Returns a list of dicts: [{"exch": "Coinbase", "symbol": "BTC-USD", "weight": 0.25}, ...]
where weights sum to ~1.0.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

import aiohttp

logger = logging.getLogger(__name__)

# Dedicated session with trust_env=True so it picks up system HTTP(S)_PROXY
# (e.g. local clash/v2ray on dev mac). On ECS where there's no env proxy,
# this falls back to direct connection — also fine.
_session: Optional[aiohttp.ClientSession] = None


async def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(trust_env=True)
    return _session


async def _http_get_json(url: str, params: Optional[dict] = None, timeout: int = 15) -> Any:
    s = await _get_session()
    async with s.get(url, params=params, timeout=timeout) as r:
        r.raise_for_status()
        return await r.json()


def _norm(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort + clamp weights to 0-1 range."""
    out = []
    for it in items:
        w = it.get("weight")
        try:
            w = float(w)
        except Exception:
            continue
        if w <= 0:
            continue
        out.append({"exch": str(it.get("exch") or "").strip(), "symbol": str(it.get("symbol") or ""), "weight": round(w, 6)})
    out.sort(key=lambda x: x["exch"].lower())
    return out


async def fetch_binance(coin: str) -> Optional[list[dict[str, Any]]]:
    # Respect BinanceClient per-group cooldown to avoid 418 loops
    from app.services.exchange.binance import _cooldown_map
    import time
    if time.time() < _cooldown_map.get("constituents", 0.0):
        return None

    sym = f"{coin}USDT"
    try:
        data = await _http_get_json(
            "https://fapi.binance.com/fapi/v1/constituents",
            params={"symbol": sym},
        )
        consts = (data or {}).get("constituents") or []
        # Binance schema: [{"exchange":"Coinbase","symbol":"BTC-USD","weight":"0.25"}]
        # Equal-weight if 'weight' missing — divide 1.0 by N
        normalized: list[dict[str, Any]] = []
        if consts and "weight" in consts[0]:
            for c_ in consts:
                normalized.append({
                    "exch": c_.get("exchange"),
                    "symbol": c_.get("symbol"),
                    "weight": c_.get("weight"),
                })
        else:
            n = len(consts) or 1
            w = 1.0 / n
            for c_ in consts:
                normalized.append({
                    "exch": c_.get("exchange"),
                    "symbol": c_.get("symbol"),
                    "weight": w,
                })
        return _norm(normalized)
    except Exception as exc:
        logger.warning("binance constituents %s failed: %s", coin, exc)
        return None


async def fetch_okx(coin: str) -> Optional[list[dict[str, Any]]]:
    try:
        resp = await _http_get_json(
            "https://www.okx.com/api/v5/market/index-components",
            params={"index": f"{coin}-USDT"},
        )
        if not isinstance(resp, dict) or resp.get("code") != "0":
            return None
        d = resp.get("data") or {}
        # OKX returns {data: {components: [...]}} (object), not a list
        if isinstance(d, list):
            d = d[0] if d else {}
        comps = (d or {}).get("components") or []
        # OKX: [{"exch":"Coinbase","symbol":"BTC-USDT","wgt":"0.25","px":"..."}]
        normalized = [
            {"exch": c_.get("exch"), "symbol": c_.get("symbol"), "weight": c_.get("wgt")}
            for c_ in comps
        ]
        return _norm(normalized)
    except Exception as exc:
        logger.warning("okx constituents %s failed: %s", coin, exc)
        return None


async def fetch_bybit(coin: str) -> Optional[list[dict[str, Any]]]:
    """Bybit has no public API for constituents.
    Use Playwright headless to render the announcement detail page.

    Lazy import: only loads if Playwright is installed (deploy-time only).
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError:
        logger.error("playwright not installed; skip bybit constituents")
        return None

    url = f"https://www.bybit.com/zh-MY/announcement-info/index-price/?symbol={coin}USDT"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = await browser.new_context(user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36")
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=30000)
            # Bybit page structure may vary; try common selectors. Tune after first run.
            # Look for table rows containing exchange + weight columns.
            rows = await page.query_selector_all("table tbody tr")
            data: list[dict[str, Any]] = []
            for r in rows:
                cells = await r.query_selector_all("td")
                if len(cells) >= 2:
                    exch = (await cells[0].inner_text()).strip()
                    weight_text = (await cells[-1].inner_text()).strip().rstrip("%")
                    try:
                        weight = float(weight_text) / 100
                        data.append({"exch": exch, "symbol": "", "weight": weight})
                    except ValueError:
                        continue
            await browser.close()
        if not data:
            logger.warning("bybit constituents %s: no rows parsed", coin)
            return None
        return _norm(data)
    except Exception as exc:
        logger.warning("bybit constituents %s failed: %s", coin, exc)
        return None


# Map exchange code → fetcher
FETCHERS = {
    "BN":  fetch_binance,
    "OKX": fetch_okx,
    "BY":  fetch_bybit,
}


def compute_overlap(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> float:
    """Sum of min(weight_a, weight_b) per shared spot exchange. Returns 0..1."""
    if not a or not b:
        return 0.0
    map_a: dict[str, float] = {}
    for it in a:
        key = (it.get("exch") or "").lower().strip()
        if key:
            map_a[key] = map_a.get(key, 0.0) + float(it.get("weight") or 0)
    total = 0.0
    seen: set[str] = set()
    for it in b:
        key = (it.get("exch") or "").lower().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        wb = float(it.get("weight") or 0)
        if key in map_a:
            total += min(map_a[key], wb)
    return round(total, 4)


def parse_json(s: Any) -> list[dict[str, Any]]:
    """Robustly parse the constituents_json column (may be dict, list, or JSON str)."""
    if not s:
        return []
    if isinstance(s, list):
        return s
    if isinstance(s, str):
        try:
            v = json.loads(s)
            return v if isinstance(v, list) else []
        except Exception:
            return []
    return []
