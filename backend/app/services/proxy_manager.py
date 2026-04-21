"""Exchange proxy manager.

Reads EXCHANGE_PROXY env var to determine proxy behavior:
- Not set or empty: no proxy (direct connection)
- "brightdata": use Bright Data rotating IP pool
- Any other value: use as literal proxy URL (e.g. "http://127.0.0.1:10080")

Usage:
    from app.services.proxy_manager import proxy_manager
    proxy_url = proxy_manager.next_proxy()  # returns str or None
"""

import logging
import os
import random
from typing import Optional

logger = logging.getLogger(__name__)

# Bright Data config (kept for backwards compat)
PROXY_HOST = "199.254.199.81"
PROXY_PORT = 22226
PROXY_PASSWORD = "wv8rvihwsbkxascoin"
PROXY_CUSTOMER = "brd-customer-hl_49cf4add-zone-data_center"
IP_POOL = [f"103.68.120.{i}" for i in range(4, 255)]


class ProxyManager:
    """Global proxy manager."""

    def __init__(self):
        self._mode = os.environ.get("EXCHANGE_PROXY", "").strip()
        self.enabled: bool = bool(self._mode)
        self._disabled_ips: set[str] = set()
        if self._mode:
            logger.info("ProxyManager: mode=%s", "brightdata" if self._mode == "brightdata" else "custom")
        else:
            logger.info("ProxyManager: disabled (no EXCHANGE_PROXY set, direct connection)")

    def _get_pool(self) -> list[str]:
        return [ip for ip in IP_POOL if ip not in self._disabled_ips]

    def disable_ip(self, ip: str):
        self._disabled_ips.add(ip)
        logger.info("ProxyManager: disabled IP %s", ip)

    def enable_ip(self, ip: str):
        self._disabled_ips.discard(ip)
        logger.info("ProxyManager: enabled IP %s", ip)

    def next_proxy(self) -> Optional[str]:
        """Get proxy URL. Returns None if disabled (direct connection)."""
        if not self.enabled:
            return None

        if self._mode == "brightdata":
            pool = self._get_pool()
            if not pool:
                logger.warning("ProxyManager: no available IPs in pool")
                return None
            ip = random.choice(pool)
            username = f"{PROXY_CUSTOMER}-ip-{ip}"
            return f"http://{username}:{PROXY_PASSWORD}@{PROXY_HOST}:{PROXY_PORT}"

        # Custom proxy URL
        return self._mode

    def status(self) -> dict:
        if self._mode == "brightdata":
            pool = self._get_pool()
            return {
                "enabled": self.enabled,
                "mode": "brightdata",
                "active_ips": len(pool),
                "disabled_ips": sorted(self._disabled_ips),
            }
        return {
            "enabled": self.enabled,
            "mode": self._mode or "direct",
        }


# Global singleton
proxy_manager = ProxyManager()
