"""Fetch perpetual index constituents for a coin from Binance / OKX / Bybit.

Usage:
    python3 index_constituents.py BTC
    python3 index_constituents.py ETH SOL DOGE     # multi
"""
import sys
import json
import urllib.request
import urllib.error


def fetch(url: str, timeout: int = 10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}", "_body": e.read().decode()[:300]}
    except Exception as e:
        return {"_error": str(e)}


def binance(coin: str):
    """GET https://fapi.binance.com/fapi/v1/constituents?symbol=COINUSDT"""
    sym = f"{coin}USDT"
    data = fetch(f"https://fapi.binance.com/fapi/v1/constituents?symbol={sym}")
    if "_error" in data:
        return data
    return {
        "symbol": data.get("symbol"),
        "time": data.get("time"),
        "constituents": [
            {"exchange": c.get("exchange"), "symbol": c.get("symbol"), "weight": c.get("weight")}
            for c in data.get("constituents", [])
        ],
    }


def okx(coin: str):
    """GET https://www.okx.com/api/v5/market/index-components?index=COIN-USDT"""
    idx = f"{coin}-USDT"
    data = fetch(f"https://www.okx.com/api/v5/market/index-components?index={idx}")
    if "_error" in data:
        return data
    if data.get("code") != "0":
        return {"_error": data.get("msg"), "_raw": data}
    d = (data.get("data") or [{}])[0]
    return {
        "index": d.get("index"),
        "ts": d.get("ts"),
        "constituents": [
            {"exchange": c.get("exch"), "symbol": c.get("symbol"), "weight": c.get("wgt")}
            for c in d.get("components", [])
        ],
    }


def bybit(coin: str):
    """Bybit doesn't expose constituents via public API. Try the internal
    announcement-info endpoint that powers https://www.bybit.com/.../index-price/
    Falls back to a clear error if it 403s."""
    # Best-effort guesses — may need manual update if Bybit changes endpoint
    candidates = [
        f"https://api2.bybit.com/announcements/api/index-price/list?baseCoin={coin}",
        f"https://api.bybit.com/v5/market/index-price-kline?category=linear&symbol={coin}USDT&interval=1&limit=1",
    ]
    for url in candidates:
        d = fetch(url)
        if "_error" not in d:
            return {"endpoint": url, "data": d}
    return {"_error": "Bybit has no public constituents API. Inspect https://www.bybit.com/zh-MY/announcement-info/index-price/ in browser DevTools to find the XHR URL, then add it here."}


def main():
    coins = sys.argv[1:] or ["BTC"]
    out = {}
    for coin in coins:
        coin = coin.upper()
        out[coin] = {
            "binance": binance(coin),
            "okx": okx(coin),
            "bybit": bybit(coin),
        }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
