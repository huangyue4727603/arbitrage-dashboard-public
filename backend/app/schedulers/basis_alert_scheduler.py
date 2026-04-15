"""Fast basis alert scheduler - independent 3-second polling.

Dedicated to basis monitoring with minimal latency.
Only requests BYBIT→BINANCE pair (single API call, ~2-3s).
Does NOT go through the slow 6-pair data_fetcher.
"""
import asyncio
import logging
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests as sync_requests
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Default thresholds
DEFAULT_THRESHOLD = -0.01     # -1% basis threshold for "新机会"
DEFAULT_MULTIPLIER = 1.2      # Significant expansion multiplier
DEFAULT_MINOR_DELTA = 0.003   # Minor expansion delta (0.3%)


def _system_sound() -> None:
    try:
        subprocess.Popen(
            ["afplay", "/System/Library/Sounds/Glass.aiff"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _system_popup(title: str, content: str) -> None:
    try:
        content = content.replace('"', '\\"').replace("'", "\\'")
        title = title.replace('"', '\\"')
        cmd = f'''osascript -e 'display dialog "{content}" with title "{title}" buttons {{"确定"}} default button "确定"' >/dev/null 2>&1 &'''
        os.system(cmd)
    except Exception:
        pass


class BasisAlertScheduler:
    """Fast 3-second basis monitoring with 3-tier alerting."""

    def __init__(self) -> None:
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        # Tracked coins: {coin_name: abs_basis_value}
        self._history: Dict[str, float] = {}
        # Alert timeline (newest first, for display)
        self._timeline: List[Dict[str, Any]] = []
        # Current basis snapshot
        self._current_basis: Dict[str, float] = {}
        # Config (loaded from DB periodically)
        self._threshold: float = DEFAULT_THRESHOLD
        self._multiplier: float = DEFAULT_MULTIPLIER
        self._minor_delta: float = DEFAULT_MINOR_DELTA
        self._blocked_coins: set = set()
        self._user_configs: Dict[int, dict] = {}  # uid -> {threshold, multiplier, blocked_coins, sound, popup}
        self._config_last_refresh: float = 0
        self._running: bool = False

    def _fetch_sync(self) -> List[Dict[str, Any]]:
        """Synchronous fetch using requests lib (~2-3s, same as user's script)."""
        api_url = f"{settings.ARBITRAGE_API_URL}/api/v1/arbitrage/chance/list"
        all_items: List[Dict[str, Any]] = []
        seen_coins: Dict[str, Dict] = {}

        pairs = [
            (["BYBIT"], ["BINANCE"]),
            (["OKX"], ["BINANCE"]),
            (["BYBIT"], ["OKX"]),
        ]

        for long_ex, short_ex in pairs:
            try:
                resp = sync_requests.post(
                    api_url,
                    json={
                        "acceptLongExchanges": long_ex,
                        "acceptShortExchanges": short_ex,
                        "allData": True,
                    },
                    timeout=8,
                )
                if resp.status_code != 200:
                    continue

                items = resp.json().get("data", [])
                for item in items:
                    if item.get("chanceType") != "LPerp_SPerp":
                        continue
                    coin = item.get("coinName", "")
                    if not coin:
                        continue
                    sp = float(item.get("shortPremium", 0))
                    if coin not in seen_coins or sp < float(seen_coins[coin].get("shortPremium", 0)):
                        seen_coins[coin] = item
            except Exception as exc:
                logger.debug("Basis alert fetch %s→%s failed: %s", long_ex, short_ex, exc)

        return list(seen_coins.values())

    async def _fetch_data(self) -> List[Dict[str, Any]]:
        """Fetch data using sync requests in thread pool (fast, ~2-5s total)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self._executor, self._fetch_sync)

    def invalidate_config(self) -> None:
        """Force config to reload on next tick."""
        self._config_last_refresh = 0

    async def _refresh_config(self) -> None:
        """Load all users' configs from DB (refresh every 5s).

        Stores per-user configs for independent threshold/notification checks.
        Global threshold uses the most lenient value for the scan pass.
        """
        import time
        now = time.time()
        if now - self._config_last_refresh < 5:
            return
        self._config_last_refresh = now

        try:
            from app.database import async_session_factory
            from app.models.alert_config import BasisAlertConfig
            from app.models.user import User
            from sqlalchemy import select

            async with async_session_factory() as db:
                result = await db.execute(
                    select(
                        BasisAlertConfig.basis_threshold,
                        BasisAlertConfig.expand_multiplier,
                        BasisAlertConfig.blocked_coins,
                        BasisAlertConfig.sound_enabled,
                        BasisAlertConfig.popup_enabled,
                        BasisAlertConfig.user_id,
                        User.sound_enabled,
                        User.popup_enabled,
                    ).join(User, User.id == BasisAlertConfig.user_id)
                )
                rows = result.all()
                if rows:
                    # Store per-user configs
                    self._user_configs = {}
                    for r in rows:
                        uid = r[5]
                        blocked = set()
                        if r[2]:
                            blocked = {c.strip().upper() for c in r[2].split(",") if c.strip()}
                        self._user_configs[uid] = {
                            "threshold": r[0] / 100,
                            "multiplier": r[1],
                            "blocked_coins": blocked,
                            "sound": r[6] and r[3],  # global AND alert
                            "popup": r[7] and r[4],   # global AND alert
                        }
                    # Global threshold = most lenient (for scan pass)
                    self._threshold = max(r[0] for r in rows) / 100
                    # Global multiplier = most sensitive
                    self._multiplier = min(r[1] for r in rows)
                    # Only block coins ALL users block
                    blocked_sets = [cfg["blocked_coins"] for cfg in self._user_configs.values()]
                    self._blocked_coins = set.intersection(*blocked_sets) if blocked_sets and all(blocked_sets) else set()
        except Exception as exc:
            logger.debug("Failed to refresh basis alert config: %s", exc)

    async def _persist_alert(self, coin: str, alert_type: str, basis: float) -> None:
        """Write alert to DB only for users whose threshold is met."""
        try:
            from app.database import async_session_factory
            from app.models.alert_history import BasisAlertHistory

            async with async_session_factory() as db:
                for uid, cfg in self._user_configs.items():
                    # Only persist if this coin's basis meets this user's threshold
                    if basis > cfg["threshold"]:
                        continue
                    if coin.upper() in cfg["blocked_coins"]:
                        continue
                    db_type = "new" if alert_type == "新机会" else "expand"
                    db.add(BasisAlertHistory(
                        user_id=uid,
                        coin_name=coin,
                        alert_type=db_type,
                        basis_value=basis * 100,
                    ))
                await db.commit()
        except Exception as exc:
            logger.debug("Failed to persist basis alert: %s", exc)

    async def _notify(self, title: str, message: str, basis: float, coin: str) -> None:
        """Send notification per user based on their own threshold and settings."""
        try:
            from app.websocket.manager import manager

            any_sound = False
            any_popup = False
            # Get currently connected user IDs
            online_uids = set(manager._user_connections.keys())

            for uid, cfg in self._user_configs.items():
                # Skip if basis doesn't meet this user's threshold
                if basis > cfg["threshold"]:
                    continue
                if coin.upper() in cfg["blocked_coins"]:
                    continue
                await manager.send_personal(uid, "alert_notification", {
                    "title": title,
                    "message": message,
                    "sound_enabled": cfg["sound"],
                    "popup_enabled": cfg["popup"],
                })
                # Only count online users for system alerts
                if uid in online_uids:
                    if cfg["sound"]:
                        any_sound = True
                    if cfg["popup"]:
                        any_popup = True
        except Exception as exc:
            logger.debug("WS notify failed: %s", exc)

        # macOS system alerts (only if online user has it enabled)
        if any_sound:
            _system_sound()
        if any_popup:
            _system_popup(title, message)

    async def tick(self) -> None:
        """Core monitoring tick - runs every 3 seconds."""
        if self._running:
            return
        self._running = True
        try:
            await self._refresh_config()
            items = await self._fetch_data()
            if not items:
                return

            now = datetime.now()
            time_str = now.strftime("%Y-%m-%d %H:%M:%S")

            for item in items:
                coin = item.get("coinName", "")
                if not coin or coin in self._blocked_coins:
                    continue

                short_premium = item.get("shortPremium")
                if short_premium is None:
                    continue

                try:
                    basis = float(short_premium)
                except (ValueError, TypeError):
                    continue

                # Update current basis snapshot
                self._current_basis[coin] = round(basis * 100, 4)

                # Only process if below threshold
                if basis > self._threshold:
                    continue

                curr_abs = abs(basis)
                funding_rate = item.get("originShortFundingRate", 0)

                if coin not in self._history:
                    # --- 新机会: first time seeing this coin below threshold ---
                    self._history[coin] = curr_abs
                    event = {
                        "coin_name": coin,
                        "alert_type": "新机会",
                        "basis": round(basis * 100, 4),
                        "time": time_str,
                        "timestamp": now.timestamp(),
                    }
                    self._timeline.insert(0, event)
                    await self._persist_alert(coin, "新机会", basis)
                    await self._notify(
                        "基差预警 - 新机会",
                        f"{coin}: 基差 {basis * 100:.3f}%",
                        basis, coin,
                    )
                    logger.info("[新机会] %s: 基差 %.3f%%", coin, basis * 100)

                else:
                    hist_abs = self._history[coin]

                    if curr_abs > hist_abs * self._multiplier:
                        # --- 显著扩大: significant expansion ---
                        self._history[coin] = curr_abs
                        event = {
                            "coin_name": coin,
                            "alert_type": "基差扩大",
                            "basis": round(basis * 100, 4),
                            "time": time_str,
                            "timestamp": now.timestamp(),
                        }
                        self._timeline.insert(0, event)
                        await self._persist_alert(coin, "基差扩大", basis)
                        await self._notify(
                            "基差预警 - 显著扩大",
                            f"{coin}: {basis * 100:.3f}% (历史: -{hist_abs * 100:.3f}%)",
                            basis, coin,
                        )
                        logger.info("[显著扩大] %s: %.3f%% (历史: -%.3f%%)",
                                    coin, basis * 100, hist_abs * 100)

                    elif curr_abs > hist_abs + self._minor_delta:
                        # --- 小幅增长: minor expansion ---
                        self._history[coin] = curr_abs
                        event = {
                            "coin_name": coin,
                            "alert_type": "基差扩大",
                            "basis": round(basis * 100, 4),
                            "time": time_str,
                            "timestamp": now.timestamp(),
                        }
                        self._timeline.insert(0, event)
                        await self._persist_alert(coin, "基差扩大", basis)
                        await self._notify(
                            "基差预警 - 小幅扩大",
                            f"{coin}: {basis * 100:.3f}%",
                            basis, coin,
                        )
                        logger.info("[小幅扩大] %s: %.3f%%", coin, basis * 100)

            # Keep timeline under 500
            if len(self._timeline) > 500:
                self._timeline = self._timeline[:500]

        except Exception as exc:
            logger.error("Basis alert tick failed: %s", exc)
        finally:
            self._running = False

    def get_timeline(self) -> List[Dict[str, Any]]:
        return self._timeline

    def get_history(self) -> Dict[str, float]:
        return self._history

    def get_current_basis(self) -> Dict[str, float]:
        return self._current_basis

    def clear(self) -> None:
        self._history = {}
        self._timeline = []
        self._current_basis = {}
        logger.info("Basis alert scheduler cleared")

    def start(self) -> None:
        if self._scheduler is not None:
            return
        self._scheduler = AsyncIOScheduler()
        self._scheduler.add_job(
            self.tick,
            trigger=IntervalTrigger(seconds=3),
            id="basis_alert_tick",
            name="Fast basis alert polling (3s)",
            replace_existing=True,
            next_run_time=datetime.now(),
        )
        self._scheduler.start()
        logger.info("Basis alert scheduler started (interval=3s, fast dedicated poller)")

    def stop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Basis alert scheduler stopped")


# Module-level singleton
basis_alert_scheduler = BasisAlertScheduler()
