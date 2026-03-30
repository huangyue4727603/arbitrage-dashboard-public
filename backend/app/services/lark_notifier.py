import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)


class LarkNotifier:
    """Send notifications to Lark (Feishu) webhook bots."""

    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=10)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def send(self, webhook_url: str, title: str, content: str) -> bool:
        """
        Send a message to Lark webhook.

        Lark webhook format:
        POST webhook_url
        Body: {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "markdown", "content": content}]
            }
        }

        Returns True on success.
        """
        session = await self._get_session()
        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {
                        "tag": "plain_text",
                        "content": title,
                    }
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content,
                    }
                ],
            },
        }
        try:
            async with session.post(webhook_url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("code") == 0 or data.get("StatusCode") == 0:
                        logger.info("Lark message sent: %s", title)
                        return True
                    else:
                        logger.warning(
                            "Lark webhook returned error: %s", data
                        )
                        return False
                else:
                    logger.warning(
                        "Lark webhook HTTP %d: %s", resp.status, await resp.text()
                    )
                    return False
        except Exception as exc:
            logger.error("Failed to send Lark message: %s", exc)
            return False

    async def send_basis_alert(
        self,
        webhook_url: str,
        coin: str,
        alert_type: str,
        basis: float,
        count: int,
    ) -> bool:
        """Send formatted basis alert."""
        title = "基差预警"
        content = (
            f"**币种**: {coin}\n"
            f"**类型**: {alert_type}\n"
            f"**基差**: {basis:.4f}%\n"
            f"**触发次数**: {count}"
        )
        return await self.send(webhook_url, title, content)

    async def send_unhedged_alert(
        self,
        webhook_url: str,
        coin: str,
        alert_type: str,
        spread: float,
        funding_diff: float,
    ) -> bool:
        """Send formatted unhedged opportunity alert."""
        title = "未对冲套利机会"
        type_label = "资费差套利" if alert_type == "type1" else "资费打开价差没打开"
        content = (
            f"**币种**: {coin}\n"
            f"**类型**: {type_label}\n"
            f"**价差**: {spread:.4f}%\n"
            f"**资费差**: {funding_diff:.4f}%"
        )
        return await self.send(webhook_url, title, content)

    async def send_post_investment_alert(
        self,
        webhook_url: str,
        coin: str,
        trigger_type: str,
        value: float,
        threshold: float,
    ) -> bool:
        """Send formatted post-investment alert."""
        title = "投后监控预警"
        type_labels = {
            "spread": "价差",
            "price": "价格",
            "oi_drop_1h": "1h持仓量下降",
            "oi_drop_4h": "4h持仓量下降",
        }
        label = type_labels.get(trigger_type, trigger_type)
        content = (
            f"**币种**: {coin}\n"
            f"**触发类型**: {label}\n"
            f"**当前值**: {value:.4f}\n"
            f"**阈值**: {threshold:.4f}"
        )
        return await self.send(webhook_url, title, content)

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None


# Module-level singleton
lark_notifier = LarkNotifier()
