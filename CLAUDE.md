# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Cryptocurrency arbitrage dashboard monitoring Binance/OKX/Bybit exchanges for funding rate spreads, basis, and price discrepancies. Written in Chinese (UI and docs).

## Commands

### Backend
```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # then fill in DATABASE_URL, JWT_SECRET, ARBITRAGE_API_URL
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev          # dev server on :5173 (proxies /api and /ws to :8000)
npm run build        # production build to dist/
npm run lint         # eslint
```

## Architecture

**Backend**: Python 3.9+ / FastAPI (async) / SQLAlchemy 2.0 (async with aiomysql) / APScheduler
**Frontend**: React 19 / TypeScript / Ant Design 6 / Vite / Zustand
**Database**: MySQL via `mysql+aiomysql` — tables auto-created on startup via `Base.metadata.create_all`

### Data Flow

The central data pipeline is in `backend/app/services/data_fetcher.py`, which fetches from an external arbitrage API (configured via `ARBITRAGE_API_URL`) every 3 seconds and caches results in memory. Multiple schedulers consume this shared cache:

```
data_fetcher (3s, trust_env=False — no proxy)
  → realtime_scheduler → basis_monitor + unhedged + post_investment + alert_engine → WebSocket broadcast
  → funding_break_scheduler (5s, reads cached data)
```

Exchange API clients (`services/exchange/{binance,okx,bybit}.py`) use proxy via `config.get_proxy()` for direct exchange access.

### Scheduler System

All schedulers live in `backend/app/schedulers/` and are started/stopped in `main.py`'s lifespan handler. Key intervals:
- **3s**: realtime (basis, unhedged, post-investment alerts)
- **5s**: funding break detection
- **5min**: kline refresh, price changes, OI snapshots
- **10min**: price trend (MA20/60/120)
- **1h**: funding rank, funding break caps

### WebSocket

Single endpoint at `/ws` (optional `?token=<jwt>` for authenticated alerts). The `websocket/manager.py` handles broadcast to all clients and targeted alerts to authenticated users. Channels: `basis_monitor`, `unhedged`, `funding_break`, `spread_update`, `new_listing`, `price_trend`, `funding_rank`, `alert_notification`.

### Frontend Structure

- `pages/` — one directory per tab (FundingRank, NewListing, FundingBreak, PriceTrend, BasisMonitor, Unhedged, AlertConfig, PremiumFilter)
- `api/` — axios client wrappers per feature, base client in `api/client.ts`
- `stores/` — Zustand stores: `authStore`, `themeStore`, `wsStore`
- `hooks/` — `useWebSocket` (realtime data), `useAuth`, `useAlertSound`

### Backend Layers

Router → Service → (data_fetcher / exchange clients) → Models/DB. Each feature module (basis_monitor, funding_rank, etc.) has parallel files in `routers/`, `services/`, and `schedulers/`.

## Key Design Decisions

- **Proxy handling**: `data_fetcher` sets `trust_env=False` (arbitrage API is direct); exchange clients use `get_proxy()` from `config.py`
- **Data filtering**: Only `LPerp_SPerp` (perpetual-to-perpetual) data is kept from the arbitrage API
- **Funding sign convention**: Long actual rate = -originLongFundingRate; Short actual rate = +originShortFundingRate; Spread = long - short
- **Python 3.9 compat**: Use `Optional[X]` not `X | None`; `from __future__ import annotations` where needed
- **K-line backfill**: Gentle rate — 2 tasks per 60s, auto-pause on Binance 418 rate limit
- **Graceful degradation**: `data_fetcher` retains last cache on API failure
