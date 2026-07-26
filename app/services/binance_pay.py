import hashlib
import hmac
import time
from urllib.parse import urlencode

import aiohttp

from app.config import settings


class BinancePayAPIError(RuntimeError):
    pass


class BinancePayClient:
    """Read-only Binance Pay history client.

    Uses the Binance USER_DATA endpoint:
    GET /sapi/v1/pay/transactions
    """

    def __init__(self) -> None:
        self.base_url = settings.BINANCE_API_BASE_URL.rstrip("/")
        self.api_key = settings.BINANCE_API_KEY.strip()
        self.api_secret = settings.BINANCE_API_SECRET.strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _signed_query(self, params: dict) -> str:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        params.setdefault("recvWindow", 10_000)

        query = urlencode(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{query}&signature={signature}"

    async def pay_transactions(
        self,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 20,
    ) -> dict:
        if not self.configured:
            raise BinancePayAPIError("BINANCE_API_KEY / BINANCE_API_SECRET are not configured.")

        params: dict[str, int] = {"limit": max(1, min(int(limit), 100))}
        if start_time_ms is not None:
            params["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            params["endTime"] = int(end_time_ms)

        url = f"{self.base_url}/sapi/v1/pay/transactions?{self._signed_query(params)}"
        headers = {"X-MBX-APIKEY": self.api_key}

        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=30) as response:
                payload = await response.json(content_type=None)

                if response.status != 200:
                    code = payload.get("code") if isinstance(payload, dict) else None
                    message = payload.get("msg") if isinstance(payload, dict) else str(payload)
                    raise BinancePayAPIError(
                        f"Binance HTTP {response.status}"
                        + (f" / code {code}" if code is not None else "")
                        + f": {message}"
                    )

                if not isinstance(payload, dict):
                    raise BinancePayAPIError("Unexpected Binance response format.")

                return payload
