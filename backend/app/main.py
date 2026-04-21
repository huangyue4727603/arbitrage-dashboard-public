import logging
import sys
from contextlib import asynccontextmanager

# Configure root logger so app loggers output INFO and above
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stderr,
)
from typing import AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.database import engine, Base, async_session_factory
from app.utils.auth import verify_token
from app.websocket.manager import manager
from app.schedulers.new_listing_scheduler import new_listing_scheduler
from app.schedulers.funding_scheduler import funding_rank_scheduler
from app.schedulers.realtime_scheduler import realtime_scheduler
from app.schedulers.price_trend_scheduler import price_trend_scheduler
from app.schedulers.funding_break_scheduler import funding_break_scheduler
from app.schedulers.oi_snapshot_scheduler import oi_snapshot_scheduler
from app.schedulers.kline_scheduler import kline_scheduler
from app.schedulers.cleanup_scheduler import cleanup_scheduler
from app.schedulers.basis_alert_scheduler import basis_alert_scheduler
from app.schedulers.index_constituents_scheduler import index_constituents_scheduler
from app.schedulers.market_history_scheduler import market_history_scheduler
from app.schedulers.data_backfill_scheduler import data_backfill_scheduler

# Import all models so they are registered with Base.metadata
import app.models  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: create tables on startup."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created")

    # Generate invite codes if none exist
    import string, random
    from sqlalchemy import select, func
    from app.models.invite_code import InviteCode
    async with async_session_factory() as db:
        count_result = await db.execute(select(func.count()).select_from(InviteCode))
        count = count_result.scalar()
        if count == 0:
            for _ in range(100):
                code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                db.add(InviteCode(code=code))
            await db.commit()
            logger.info("Generated 100 invite codes")
    new_listing_scheduler.start()
    funding_rank_scheduler.start()
    realtime_scheduler.start()
    price_trend_scheduler.start()
    funding_break_scheduler.start()
    oi_snapshot_scheduler.start()
    kline_scheduler.start()
    basis_alert_scheduler.start()
    cleanup_scheduler.start()
    index_constituents_scheduler.start()
    market_history_scheduler.start()
    # Start background data backfill (runs once, fills gaps across all data types)
    data_backfill_scheduler.start_background()
    # Preload caches so first page load isn't empty
    import asyncio as _asyncio
    _asyncio.create_task(kline_scheduler.refresh_price_changes())
    _asyncio.create_task(kline_scheduler.refresh_funding_cumulative())
    yield
    data_backfill_scheduler.stop()
    market_history_scheduler.stop()
    index_constituents_scheduler.stop()
    cleanup_scheduler.stop()
    basis_alert_scheduler.stop()
    kline_scheduler.stop()
    oi_snapshot_scheduler.stop()
    funding_break_scheduler.stop()
    price_trend_scheduler.stop()
    realtime_scheduler.stop()
    funding_rank_scheduler.stop()
    new_listing_scheduler.stop()
    await engine.dispose()
    logger.info("Database engine disposed")


app = FastAPI(
    title="Arbitrage Dashboard API",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware - allow all origins for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
from app.routers.auth import router as auth_router  # noqa: E402
from app.routers.settings import router as settings_router  # noqa: E402
from app.routers.new_listing import router as new_listing_router  # noqa: E402
from app.routers.funding_rank import router as funding_rank_router  # noqa: E402
from app.routers.basis_monitor import router as basis_monitor_router  # noqa: E402
from app.routers.unhedged import router as unhedged_router  # noqa: E402
from app.routers.price_trend import router as price_trend_router  # noqa: E402
from app.routers.funding_break import router as funding_break_router  # noqa: E402
from app.routers.alert import router as alert_router  # noqa: E402
from app.routers.premium_filter import router as premium_filter_router  # noqa: E402

app.include_router(auth_router)
app.include_router(settings_router)
app.include_router(new_listing_router)
app.include_router(funding_rank_router)
app.include_router(basis_monitor_router)
app.include_router(unhedged_router)
app.include_router(price_trend_router)
app.include_router(funding_break_router)
app.include_router(alert_router)
app.include_router(premium_filter_router)


@app.get("/api/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint. Optionally authenticate via token query param.
    Connect: ws://host/ws?token=<jwt_token>
    """
    token = websocket.query_params.get("token")
    user_id = None

    if token:
        payload = verify_token(token)
        if payload and payload.get("sub"):
            user_id = int(payload["sub"])

    await manager.connect(websocket, user_id)
    try:
        while True:
            # Keep connection alive; handle incoming messages if needed
            data = await websocket.receive_text()
            # Echo back for now; extend with command handling as needed
            logger.debug("WS received from user %s: %s", user_id, data)
    except WebSocketDisconnect:
        manager.disconnect(websocket, user_id)
