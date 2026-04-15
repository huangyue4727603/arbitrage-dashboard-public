import logging
import os
import subprocess
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default config for users who haven't customized
DEFAULT_THRESHOLD = -1.0    # -1%
DEFAULT_MULTIPLIER = 1.1


class BasisMonitorService:
    """Monitor basis (premium) data and generate alerts.

    In-memory state for real-time display. Alerts also written to DB
    for historical records via persist_alerts().
    """

    def __init__(self) -> None:
        # Tracked coins: {coin_name: {min_basis, alert_count, last_alert_at}}
        self._records: Dict[str, Dict[str, Any]] = {}
        # Timeline events (newest first)
        self._timeline: List[Dict[str, Any]] = []
        # Current basis for all coins (updated every 3s)
        self._current_basis: Dict[str, float] = {}
        # Temp blocked coins per user (in-memory, cleared on clear)
        self._temp_blocked: Dict[int, set] = {}
        # Pending alerts to write to DB
        self._pending_db_alerts: List[Dict[str, Any]] = []

    def process_data(self, api_data: Dict[str, Any]) -> None:
        """Process data from realtime_scheduler and update state."""
        now = datetime.now()

        # Extract basis from all exchange pairs
        basis_map: Dict[str, float] = {}
        for pair_key, pair_data in api_data.items():
            if not isinstance(pair_data, dict):
                continue
            items = pair_data.get("data", [])
            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue
                coin_name = item.get("coinName", "")
                short_premium = item.get("shortPremium")
                if not coin_name or short_premium is None:
                    continue
                try:
                    basis = float(short_premium) * 100
                except (ValueError, TypeError):
                    continue

                if coin_name not in basis_map or basis < basis_map[coin_name]:
                    basis_map[coin_name] = round(basis, 4)

        self._current_basis = basis_map

        capture_threshold = -0.1

        for coin_name, basis in basis_map.items():
            if basis >= capture_threshold:
                continue

            record = self._records.get(coin_name)

            if record is None:
                self._records[coin_name] = {
                    "min_basis": basis,
                    "alert_count": 1,
                    "last_alert_at": now,
                }
                event = {
                    "coin_name": coin_name,
                    "alert_type": "新机会",
                    "basis": basis,
                    "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp": now.timestamp(),
                }
                self._timeline.insert(0, event)
                self._pending_db_alerts.append(event)
            else:
                if basis < record["min_basis"] * 1.05:
                    record["min_basis"] = basis
                    record["alert_count"] += 1
                    record["last_alert_at"] = now
                    event = {
                        "coin_name": coin_name,
                        "alert_type": "基差扩大",
                        "basis": basis,
                        "time": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "timestamp": now.timestamp(),
                    }
                    self._timeline.insert(0, event)
                    self._pending_db_alerts.append(event)

        if len(self._timeline) > 500:
            self._timeline = self._timeline[:500]

    async def persist_alerts(self) -> None:
        """Write pending alerts to DB and push WebSocket notifications."""
        if not self._pending_db_alerts:
            return

        alerts_to_write = self._pending_db_alerts[:]
        self._pending_db_alerts = []

        try:
            from app.database import async_session_factory
            from app.models.alert_history import BasisAlertHistory
            from app.models.alert_config import BasisAlertConfig
            from app.models.user import User
            from app.websocket.manager import manager
            from sqlalchemy import select

            async with async_session_factory() as db:
                # Get all users with basis config + global settings
                result = await db.execute(
                    select(
                        BasisAlertConfig.user_id,
                        BasisAlertConfig.basis_threshold,
                        BasisAlertConfig.sound_enabled,
                        BasisAlertConfig.popup_enabled,
                        BasisAlertConfig.blocked_coins,
                        User.sound_enabled,
                        User.popup_enabled,
                    )
                    .join(User, User.id == BasisAlertConfig.user_id)
                )
                user_configs = result.all()

                if not user_configs:
                    return

                # Collect alerts per user for batched notification
                user_alert_coins: dict = {}  # uid -> list of alert summaries

                for alert in alerts_to_write:
                    alert_type_db = "new" if alert["alert_type"] == "新机会" else "expand"

                    for (uid, threshold, alert_sound, alert_popup,
                         blocked_str, global_sound, global_popup) in user_configs:

                        # Check blocked coins
                        if blocked_str:
                            blocked = {c.strip().upper() for c in blocked_str.split(",") if c.strip()}
                            if alert["coin_name"].upper() in blocked:
                                continue

                        # Check threshold
                        if alert["basis"] >= threshold:
                            continue

                        # Write to DB
                        db.add(BasisAlertHistory(
                            user_id=uid,
                            coin_name=alert["coin_name"],
                            alert_type=alert_type_db,
                            basis_value=alert["basis"],
                        ))

                        # Collect for batched notification
                        if uid not in user_alert_coins:
                            user_alert_coins[uid] = {
                                "coins": [],
                                "should_sound": global_sound and alert_sound,
                                "should_popup": global_popup and alert_popup,
                            }
                        user_alert_coins[uid]["coins"].append(
                            f"{alert['coin_name']}({alert['alert_type']} {alert['basis']:.4f}%)"
                        )

                # Send one batched notification per user
                for uid, info in user_alert_coins.items():
                    if info["should_sound"] or info["should_popup"]:
                        coins_summary = info["coins"]
                        if len(coins_summary) > 5:
                            display = ", ".join(coins_summary[:5]) + f" 等{len(coins_summary)}个"
                        else:
                            display = ", ".join(coins_summary)

                        title = f"基差预警 ({len(coins_summary)}条)"

                        # Browser WebSocket notification
                        await manager.send_personal(uid, "alert_notification", {
                            "title": title,
                            "message": display,
                            "sound_enabled": info["should_sound"],
                            "popup_enabled": info["should_popup"],
                        })

                        # macOS system alerts removed - handled per-user via WebSocket

                        logger.info("Sent basis alert notification to user %d: %d coins", uid, len(coins_summary))

                await db.commit()
                logger.info("Persisted %d basis alerts for %d users", len(alerts_to_write), len(user_configs))
        except Exception as exc:
            logger.error("Failed to persist basis alerts: %s", exc)

    def get_data(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        multiplier: float = DEFAULT_MULTIPLIER,
    ) -> Dict[str, Any]:
        """Get filtered data for a specific user's config."""
        filtered_records = []
        for coin_name, record in self._records.items():
            if record["min_basis"] < threshold:
                filtered_records.append({
                    "coin_name": coin_name,
                    "current_basis": self._current_basis.get(coin_name),
                    "min_basis": record["min_basis"],
                    "alert_count": record["alert_count"],
                    "last_alert_at": record["last_alert_at"].strftime("%Y-%m-%d %H:%M:%S"),
                })

        filtered_records.sort(key=lambda x: x["min_basis"])

        filtered_timeline = [e for e in self._timeline if e["basis"] < threshold][:200]

        return {
            "records": filtered_records,
            "timeline": filtered_timeline,
        }

    def clear(self) -> None:
        """Clear all records, timeline, and temp blocked coins."""
        self._records = {}
        self._timeline = []
        self._current_basis = {}
        self._temp_blocked = {}
        self._pending_db_alerts = []
        logger.info("Basis monitor cleared")

    def set_temp_blocked(self, user_id: int, coins: set) -> None:
        self._temp_blocked[user_id] = coins

    def get_temp_blocked(self, user_id: int) -> set:
        return self._temp_blocked.get(user_id, set())

    def get_coin_alerts(self, coin_name: str) -> List[Dict[str, Any]]:
        return [e for e in self._timeline if e["coin_name"] == coin_name]

    def get_current_basis(self) -> Dict[str, float]:
        return self._current_basis


def _system_sound() -> None:
    """Play macOS system alert sound (non-blocking)."""
    try:
        subprocess.Popen(
            ["afplay", "/System/Library/Sounds/Glass.aiff"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _system_popup(title: str, content: str) -> None:
    """Show macOS system dialog (non-blocking)."""
    try:
        # Escape quotes for osascript
        content = content.replace('"', '\\"').replace("'", "\\'")
        title = title.replace('"', '\\"')
        cmd = f'''osascript -e 'display dialog "{content}" with title "{title}" buttons {{"确定"}} default button "确定"' >/dev/null 2>&1 &'''
        os.system(cmd)
    except Exception:
        pass


# Module-level singleton
basis_monitor_service = BasisMonitorService()
