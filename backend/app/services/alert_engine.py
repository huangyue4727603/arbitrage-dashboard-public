import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models.alert_config import (
    BasisAlertConfig,
    PostInvestmentMonitor,
    UnhedgedAlertConfig,
)
from app.models.alert_history import BasisAlertHistory, BasisAlertRecord
from app.models.lark_bot import LarkBot
from app.models.market_data import OISnapshot
from app.services.lark_notifier import lark_notifier
from app.websocket.manager import manager

logger = logging.getLogger(__name__)


class AlertEngine:
    """Unified alert processing engine that handles notifications for all alert types."""

    def __init__(self) -> None:
        # Cache OI drop values: {coin_name: {"1h": float, "4h": float}}
        self._oi_cache: Dict[str, Dict[str, Optional[float]]] = {}
        # Post-investment alert cooldown: {monitor_id_trigger_type: last_alert_time}
        self._post_invest_cooldown: Dict[str, datetime] = {}
        self._post_invest_cooldown_seconds = 300  # 5 minutes

    async def process_basis_alert(self, alert_data: Dict[str, Any]) -> None:
        """
        For each user with basis alert config:
        - Check if coin is in blocked list
        - Apply user's personalized thresholds
        - If alert triggers:
          - Save to basis_alert_history
          - Send notifications (check global sound/popup + per-config settings)
          - Push WebSocket notification to user
        """
        async with async_session_factory() as db:
            try:
                # Get all basis alert configs
                result = await db.execute(select(BasisAlertConfig))
                configs = result.scalars().all()

                for config in configs:
                    user_id = config.user_id
                    threshold = config.basis_threshold  # e.g. -1.0
                    multiplier = config.expand_multiplier  # e.g. 1.1

                    # Parse blocked coins
                    blocked: List[str] = []
                    if config.blocked_coins:
                        blocked = [
                            c.strip().upper()
                            for c in config.blocked_coins.split(",")
                            if c.strip()
                        ]

                    for alert in alert_data.get("alerts", []):
                        coin_name = alert.get("coin_name", "")
                        if not coin_name:
                            continue

                        # Skip blocked coins
                        if coin_name.upper() in blocked:
                            continue

                        basis = alert.get("current_basis", 0.0)

                        # Apply user's threshold
                        if basis >= threshold:
                            continue

                        alert_type = alert.get("alert_type", "新机会")
                        alert_count = alert.get("alert_count", 1)

                        # Save to history
                        history = BasisAlertHistory(
                            user_id=user_id,
                            coin_name=coin_name,
                            alert_type=alert_type,
                            basis_value=basis,
                        )
                        db.add(history)

                        # Build notification
                        title = "基差预警"
                        content = (
                            f"币种: {coin_name}\n"
                            f"类型: {alert_type}\n"
                            f"基差: {basis:.4f}%\n"
                            f"触发次数: {alert_count}"
                        )

                        await self._send_notification(
                            user_id=user_id,
                            config={
                                "sound_enabled": config.sound_enabled,
                                "popup_enabled": config.popup_enabled,
                                "lark_bot_id": config.lark_bot_id,
                            },
                            title=title,
                            content=content,
                            channel="basisAlert",
                            alert_payload=alert,
                            db=db,
                        )

                await db.commit()
            except Exception as exc:
                logger.error("process_basis_alert failed: %s", exc)
                await db.rollback()

    async def process_unhedged_alert(self, alert_data: Dict[str, Any]) -> None:
        """
        For each user with unhedged alert config enabled:
        - Send notifications based on config
        - Push WebSocket notification
        """
        alerts = alert_data.get("alerts", [])
        if not alerts:
            return

        async with async_session_factory() as db:
            try:
                result = await db.execute(select(UnhedgedAlertConfig))
                configs = result.scalars().all()

                for config in configs:
                    user_id = config.user_id

                    for alert in alerts:
                        coin = alert.get("coin", "")
                        alert_type = alert.get("type", "")
                        spread = alert.get("spread", 0.0)
                        funding_diff = alert.get("funding_diff", 0.0)

                        title = "未对冲套利机会"
                        type_label = (
                            "资费差套利"
                            if alert_type == "type1"
                            else "资费打开价差没打开"
                        )
                        content = (
                            f"币种: {coin}\n"
                            f"类型: {type_label}\n"
                            f"价差: {spread:.4f}%\n"
                            f"资费差: {funding_diff:.4f}%"
                        )

                        await self._send_notification(
                            user_id=user_id,
                            config={
                                "sound_enabled": config.sound_enabled,
                                "popup_enabled": config.popup_enabled,
                                "lark_bot_id": config.lark_bot_id,
                            },
                            title=title,
                            content=content,
                            channel="unhedgedAlert",
                            alert_payload=alert,
                            db=db,
                        )

                await db.commit()
            except Exception as exc:
                logger.error("process_unhedged_alert failed: %s", exc)
                await db.rollback()

    async def process_post_investment(self, api_data: Dict[str, Any]) -> None:
        """
        For each active post-investment monitor:
        - Find matching coin in API data
        - Check spread threshold: spread < threshold -> alert
        - Check price threshold: price < threshold -> alert
        - Check OI drop 1h/4h: query from DB -> alert
        - If any triggers: send notification per monitor config
        """
        async with async_session_factory() as db:
            try:
                # Get all active monitors
                result = await db.execute(
                    select(PostInvestmentMonitor).where(
                        PostInvestmentMonitor.is_active == True  # noqa: E712
                    )
                )
                monitors = result.scalars().all()
                logger.info("process_post_investment: %d active monitors", len(monitors))

                if not monitors:
                    return

                # Build coin data lookup from API data
                coin_data: Dict[str, Dict[str, Any]] = {}
                for pair_key, pair_data in api_data.items():
                    if not pair_data or not isinstance(pair_data, dict):
                        continue
                    items = pair_data.get("data", pair_data)
                    if isinstance(items, dict):
                        items = items.get("data", [])
                    if not isinstance(items, list):
                        continue

                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        coin_name = (
                            item.get("symbolName", "")
                            or item.get("coinName", "")
                            or item.get("coin_name", "")
                        )
                        if not coin_name:
                            continue

                        long_ex = item.get(
                            "longExchange",
                            pair_key.split("_")[0] if "_" in pair_key else "",
                        )
                        short_ex = item.get(
                            "shortExchange",
                            pair_key.split("_")[1] if "_" in pair_key else "BINANCE",
                        )
                        key = f"{coin_name.upper()}_{long_ex.upper()}_{short_ex.upper()}"
                        coin_data[key] = item

                for monitor in monitors:
                    lookup_key = (
                        f"{monitor.coin_name.upper()}"
                        f"_{monitor.long_exchange.upper()}"
                        f"_{monitor.short_exchange.upper()}"
                    )
                    item = coin_data.get(lookup_key)
                    if item is None:
                        continue

                    triggers: List[Dict[str, Any]] = []

                    # Check spread threshold
                    if monitor.spread_threshold is not None:
                        try:
                            a3 = float(item.get("bid", 0))
                            b3 = float(item.get("ask", 0))
                            if a3 > 0:
                                spread = (b3 - a3) / a3 * 100
                                if spread < monitor.spread_threshold:
                                    triggers.append(
                                        {
                                            "trigger_type": "spread",
                                            "value": spread,
                                            "threshold": monitor.spread_threshold,
                                        }
                                    )
                        except (ValueError, TypeError):
                            pass

                    # Check price threshold
                    if monitor.price_threshold is not None:
                        try:
                            price = float(
                                item.get("bid", 0) or item.get("price", 0)
                            )
                            if price > 0 and price < monitor.price_threshold:
                                triggers.append(
                                    {
                                        "trigger_type": "price",
                                        "value": price,
                                        "threshold": monitor.price_threshold,
                                    }
                                )
                        except (ValueError, TypeError):
                            pass

                    # Check OI drop 1h (from DB)
                    if monitor.oi_drop_1h_threshold is not None:
                        oi_drop = await self._fetch_oi_drop_from_db(db, monitor.user_id, monitor.coin_name, "1h")
                        self._oi_cache.setdefault(monitor.coin_name.upper(), {})["1h"] = oi_drop
                        if oi_drop is not None and oi_drop < monitor.oi_drop_1h_threshold:
                            triggers.append(
                                {
                                    "trigger_type": "oi_drop_1h",
                                    "value": oi_drop,
                                    "threshold": monitor.oi_drop_1h_threshold,
                                }
                            )

                    # Check OI drop 4h (from DB)
                    if monitor.oi_drop_4h_threshold is not None:
                        oi_drop = await self._fetch_oi_drop_from_db(db, monitor.user_id, monitor.coin_name, "4h")
                        self._oi_cache.setdefault(monitor.coin_name.upper(), {})["4h"] = oi_drop
                        if oi_drop is not None and oi_drop < monitor.oi_drop_4h_threshold:
                            triggers.append(
                                {
                                    "trigger_type": "oi_drop_4h",
                                    "value": oi_drop,
                                    "threshold": monitor.oi_drop_4h_threshold,
                                }
                            )

                    # Send notifications for all triggers (with cooldown)
                    for trigger in triggers:
                        cooldown_key = f"{monitor.id}_{trigger['trigger_type']}"
                        now = datetime.now()
                        last_alert = self._post_invest_cooldown.get(cooldown_key)
                        if last_alert and (now - last_alert).total_seconds() < self._post_invest_cooldown_seconds:
                            continue

                        title = "投后监控预警"
                        type_labels = {
                            "spread": "价差",
                            "price": "价格",
                            "oi_drop_1h": "1h持仓量下降",
                            "oi_drop_4h": "4h持仓量下降",
                        }
                        label = type_labels.get(
                            trigger["trigger_type"], trigger["trigger_type"]
                        )
                        content = (
                            f"币种: {monitor.coin_name}\n"
                            f"触发类型: {label}\n"
                            f"当前值: {trigger['value']:.4f}\n"
                            f"阈值: {trigger['threshold']:.4f}"
                        )

                        logger.info(
                            "Post-investment alert: coin=%s, type=%s, value=%.4f, threshold=%.4f, user=%d",
                            monitor.coin_name, trigger["trigger_type"],
                            trigger["value"], trigger["threshold"], monitor.user_id,
                        )

                        await self._send_notification(
                            user_id=monitor.user_id,
                            config={
                                "sound_enabled": monitor.sound_enabled,
                                "popup_enabled": monitor.popup_enabled,
                                "lark_bot_id": monitor.lark_bot_id,
                            },
                            title=title,
                            content=content,
                            channel="postInvestmentAlert",
                            alert_payload={
                                "coin_name": monitor.coin_name,
                                "long_exchange": monitor.long_exchange,
                                "short_exchange": monitor.short_exchange,
                                **trigger,
                            },
                            db=db,
                        )
                        self._post_invest_cooldown[cooldown_key] = now

                await db.commit()
            except Exception as exc:
                logger.error("process_post_investment failed: %s", exc)
                await db.rollback()

    async def _fetch_oi_drop_from_db(
        self, db: AsyncSession, user_id: int, coin_name: str, interval: str
    ) -> Optional[float]:
        """Query OI drop percentage from arb_oi_snapshots.

        Formula: (current_oi - max_oi) / max_oi * 100
        Returns a negative value when OI drops (e.g. -20 means dropped 20%).
        """
        symbol = f"{coin_name.upper()}USDT"

        try:
            result = await db.execute(
                select(OISnapshot)
                .where(OISnapshot.user_id == user_id)
                .where(OISnapshot.symbol == symbol)
            )
            row = result.scalar_one_or_none()

            if row is None:
                return None

            current_oi = row.current_oi
            max_oi = row.max_oi_1h if interval == "1h" else row.max_oi_4h

            if max_oi <= 0:
                return None

            drop_pct = (current_oi - max_oi) / max_oi * 100
            return round(drop_pct, 4)
        except Exception as exc:
            logger.debug("Failed to query OI for %s (%s): %s", symbol, interval, exc)
            return None

    async def _send_notification(
        self,
        user_id: int,
        config: Dict[str, Any],
        title: str,
        content: str,
        channel: str,
        alert_payload: Dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Send notification through configured channels (sound/popup via WS, Lark via webhook)."""
        # Check user's global notification settings
        from app.models.user import User
        user_result = await db.execute(
            select(User.sound_enabled, User.popup_enabled)
            .where(User.id == user_id)
        )
        user_row = user_result.first()
        global_sound = user_row[0] if user_row else True
        global_popup = user_row[1] if user_row else True

        # WebSocket notification with sound/popup flags
        ws_data = {
            "title": title,
            "content": content,
            "sound_enabled": global_sound and config.get("sound_enabled", True),
            "popup_enabled": global_popup and config.get("popup_enabled", True),
            "alert": alert_payload,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        await manager.send_personal(user_id, channel, ws_data)

        # Lark notification
        lark_bot_id = config.get("lark_bot_id")
        if lark_bot_id is not None:
            try:
                result = await db.execute(
                    select(LarkBot).where(LarkBot.id == lark_bot_id)
                )
                bot = result.scalar_one_or_none()
                if bot is not None:
                    await lark_notifier.send(bot.webhook_url, title, content)
            except Exception as exc:
                logger.error(
                    "Failed to send Lark notification (bot_id=%d): %s",
                    lark_bot_id,
                    exc,
                )


    def get_oi_cache(self) -> Dict[str, Dict[str, Optional[float]]]:
        """Return cached OI drop values. Updated every ~3s by realtime scheduler."""
        return self._oi_cache


# Module-level singleton
alert_engine = AlertEngine()
