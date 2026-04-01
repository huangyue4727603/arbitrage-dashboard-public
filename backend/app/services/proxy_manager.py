"""Bright Data forward proxy with random IP selection.

Uses full 103.68.120.4-254 IP pool, randomly picks an IP per request
to maximize distribution across all available IPs.

Usage:
    from app.services.proxy_manager import proxy_manager
    proxy_url = proxy_manager.next_proxy()  # returns str or None if disabled
"""

import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)

PROXY_HOST = "199.254.199.81"
PROXY_PORT = 22226
PROXY_PASSWORD = "wv8rvihwsbkxascoin"
PROXY_CUSTOMER = "brd-customer-hl_49cf4add-zone-data_center"

# Full available pool: 103.68.120.4 - 103.68.120.254 (251 IPs)
IP_POOL = [f"103.68.120.{i}" for i in range(4, 255)]


class ProxyManager:
    """Global proxy manager with random IP selection."""

    def __init__(self):
        self.enabled: bool = True
        self._disabled_ips: set[str] = set()

    def _get_pool(self) -> list[str]:
        return [ip for ip in IP_POOL if ip not in self._disabled_ips]

    def disable_ip(self, ip: str):
        self._disabled_ips.add(ip)
        logger.info("ProxyManager: disabled IP %s", ip)

    def enable_ip(self, ip: str):
        self._disabled_ips.discard(ip)
        logger.info("ProxyManager: enabled IP %s", ip)

    def next_proxy(self) -> Optional[str]:
        """Get a random proxy URL. Returns None if disabled."""
        if not self.enabled:
            return None
        pool = self._get_pool()
        if not pool:
            logger.warning("ProxyManager: no available IPs in pool")
            return None
        ip = random.choice(pool)
        username = f"{PROXY_CUSTOMER}-ip-{ip}"
        return f"http://{username}:{PROXY_PASSWORD}@{PROXY_HOST}:{PROXY_PORT}"

    def status(self) -> dict:
        pool = self._get_pool()
        return {
            "enabled": self.enabled,
            "total_ips": len(IP_POOL),
            "active_ips": len(pool),
            "disabled_ips": sorted(self._disabled_ips),
        }


# Global singleton
proxy_manager = ProxyManager()
