import hmac
import hashlib
import json
from typing import Any
import aiohttp
from app.config import settings


class NowPayments:
    BASE_URL = "https://api.nowpayments.io/v1"
    CURRENCY_ALIASES = {"usdtbep20": "usdtbsc", "usdttrc20": "usdttrc20"}

    def __init__(self) -> None:
        self.api_key = settings.NOWPAYMENTS_API_KEY

    def normalize_currency(self, value: str) -> str:
        return self.CURRENCY_ALIASES.get(value.lower(), value.lower())

    async def create_payment(self, order_id: int | str, price_amount: float, price_currency: str,
                             pay_currency: str, description: str) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("NOWPAYMENTS_API_KEY is not configured")
        api_currency = self.normalize_currency(pay_currency)
        payload = {
            "price_amount": float(price_amount),
            "price_currency": price_currency.lower(),
            "pay_currency": api_currency,
            "order_id": str(order_id),
            "order_description": description,
            "ipn_callback_url": settings.webhook_url,
        }
        headers = {"x-api-key": self.api_key, "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{self.BASE_URL}/payment", json=payload, headers=headers, timeout=30) as resp:
                data = await resp.json(content_type=None)
                if resp.status >= 400:
                    code = str(data.get("code") or "") if isinstance(data, dict) else ""
                    if code == "AMOUNT_MINIMAL_ERROR":
                        raise RuntimeError(
                            "This order is below NOWPayments' current network minimum. "
                            "Increase quantity or choose Binance, Wallet, or UPI."
                        )
                    raise RuntimeError(f"NOWPayments payment error for {api_currency.upper()}: {data}")
                return data


def verify_ipn(raw_body: bytes, signature: str | None) -> bool:
    if not settings.NOWPAYMENTS_IPN_SECRET or not signature:
        return False
    try:
        body = json.loads(raw_body.decode("utf-8"))
        sorted_body = json.dumps(body, separators=(",", ":"), sort_keys=True)
    except Exception:
        return False
    digest = hmac.new(settings.NOWPAYMENTS_IPN_SECRET.encode("utf-8"), sorted_body.encode("utf-8"), hashlib.sha512).hexdigest()
    return hmac.compare_digest(digest, signature)
