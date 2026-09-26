import logging
from typing import Any
import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)


class EkQRClient:
    """Client for EkQR / UPIGateway dynamic QR creation and verification."""

    def __init__(self) -> None:
        self.base_url = getattr(settings, "EKQR_BASE_URL", "https://api.ekqr.in").rstrip("/")

    @property
    def api_key(self) -> str:
        return getattr(settings, "EKQR_API_KEY", "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    async def create_order(
        self,
        *,
        order_id: int,
        amount_inr: int | float,
        product_name: str,
        customer_name: str = "Customer",
        customer_email: str | None = None,
        customer_mobile: str = "9999999999",
        redirect_url: str | None = None,
    ) -> dict[str, Any] | None:
        """Create a dynamic payment order with EkQR API."""
        if not self.is_configured():
            logger.info("EkQR API key is not configured; skipping dynamic order creation.")
            return None

        client_txn_id = f"PRIME_{order_id}"
        email = customer_email or f"user_{order_id}@primehub.local"
        bot_user = getattr(settings, "TELEGRAM_BOT_USERNAME", "PrimeHubUs_Bot") or "PrimeHubUs_Bot"
        red_url = redirect_url or f"https://t.me/{bot_user}"

        payload = {
            "key": self.api_key,
            "client_txn_id": client_txn_id,
            "amount": str(int(round(float(amount_inr)))),
            "p_info": (product_name or "Digital Subscription")[:40],
            "customer_name": (customer_name or "Prime Customer")[:30],
            "customer_email": email,
            "customer_mobile": customer_mobile,
            "redirect_url": red_url,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/create_order",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json(content_type=None)
                    if data.get("status") and isinstance(data.get("data"), dict):
                        logger.info(f"EkQR order created successfully for Order #{order_id}")
                        return data["data"]
                    logger.warning(f"EkQR create_order failed for #{order_id}: {data}")
                    return None
        except Exception as exc:
            logger.exception(f"EkQR create_order connection error for #{order_id}: {exc}")
            return None

    async def check_order_status(
        self,
        *,
        order_id: int,
        txn_date_str: str | None = None,
    ) -> dict[str, Any] | None:
        """Check order status with EkQR API."""
        if not self.is_configured():
            return None

        from datetime import datetime, timezone
        client_txn_id = f"PRIME_{order_id}"
        date_str = txn_date_str or datetime.now(timezone.utc).strftime("%d-%m-%Y")

        payload = {
            "key": self.api_key,
            "client_txn_id": client_txn_id,
            "txn_date": date_str,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/check_order_status",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    data = await resp.json(content_type=None)
                    if data.get("status") and isinstance(data.get("data"), dict):
                        return data["data"]
                    return None
        except Exception as exc:
            logger.exception(f"EkQR check_order_status error for #{order_id}: {exc}")
            return None


ekqr_client = EkQRClient()
