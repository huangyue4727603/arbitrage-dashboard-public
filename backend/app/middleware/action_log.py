"""Middleware to log all API requests to arb_user_action_log table."""
import asyncio
import logging
import time
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.utils.auth import verify_token

logger = logging.getLogger(__name__)

# Auto-refresh polling endpoints — skip logging
SKIP_PATHS = {
    "/api/health",
    "/api/funding-rank/realtime",
    "/api/funding-rank/price-changes",
    "/api/funding-rank/oi-lsr",
    "/api/funding-rank/index-overlap",
    "/api/funding-rank/bn-index-weights",
    "/api/funding-rank/bn-spot",
    "/api/funding-break",
    "/api/basis-monitor",
    "/api/basis-monitor/coin-alerts",
    "/api/basis-monitor/config",
    "/api/price-trend",
    "/api/new-listing",
    "/api/unhedged",
    "/api/premium-filter",
    "/api/premium-filter/basis",
    "/api/auth/me",
    "/api/settings/notification",
    "/api/settings/theme",
}


class ActionLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip non-API paths
        if not path.startswith("/api"):
            return await call_next(request)

        # Skip auto-refresh polling endpoints (only log user-initiated actions)
        if path in SKIP_PATHS:
            return await call_next(request)

        # Skip GET requests to common list/query endpoints (auto-refresh)
        if request.method == "GET" and path.startswith("/api/funding-rank") and path not in (
            "/api/funding-rank/detail",
            "/api/funding-rank/watchlist",
            "/api/funding-rank/index-detail",
            "/api/funding-rank/coins",
        ):
            return await call_next(request)

        t0 = time.time()

        # Extract user_id from token (non-blocking)
        user_id: Optional[int] = None
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            payload = verify_token(auth[7:])
            if payload and payload.get("sub"):
                try:
                    user_id = int(payload["sub"])
                except (ValueError, TypeError):
                    pass

        # Read body for POST/PUT/DELETE (limit size)
        body_str: Optional[str] = None
        if request.method in ("POST", "PUT", "DELETE"):
            try:
                body_bytes = await request.body()
                if len(body_bytes) <= 2000:
                    body_str = body_bytes.decode("utf-8", errors="ignore")
            except Exception:
                pass

        # Execute request
        response = await call_next(request)

        duration_ms = int((time.time() - t0) * 1000)

        # Log to DB in background (don't block response)
        asyncio.create_task(self._save_log(
            user_id=user_id,
            method=request.method,
            path=path,
            query=str(request.url.query) if request.url.query else None,
            body=body_str,
            status_code=response.status_code,
            ip=request.headers.get("x-real-ip") or request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent", "")[:500],
            duration_ms=duration_ms,
        ))

        return response

    @staticmethod
    async def _save_log(**kwargs) -> None:
        try:
            from sqlalchemy.dialects.mysql import insert as mysql_insert
            from app.database import async_session_factory
            from app.models.market_data import UserActionLog

            async with async_session_factory() as db:
                await db.execute(
                    mysql_insert(UserActionLog).values(**kwargs)
                )
                await db.commit()
        except Exception:
            pass  # Never let logging break the app
