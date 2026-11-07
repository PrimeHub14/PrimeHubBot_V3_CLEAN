from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)


class CupponsHubError(RuntimeError):
    pass


def is_cupponshub_product(product) -> bool:
    if not product:
        return False
    return bool(getattr(product, "cupponshub_product_id", None))


def get_cupponshub_target_id(product) -> str | None:
    if not product:
        return None
    val = getattr(product, "cupponshub_product_id", None)
    return str(val).strip() if val else None


class CupponsHubClient:
    def __init__(self) -> None:
        self.base_url = (getattr(settings, "CUPPONSHUB_BASE_URL", "") or "https://cupponhub.shop/reseller/api").rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=getattr(settings, "CUPPONSHUB_TIMEOUT_SECONDS", 20))
        self._cached_products: list[dict[str, Any]] = []
        self._cache_time: float = 0.0
        self._stock_map: dict[str, int] = {}
        self._lock = asyncio.Lock()

    @property
    def api_key(self) -> str:
        return (getattr(settings, "CUPPONSHUB_API_KEY", "") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        if not self.api_key:
            raise CupponsHubError("Cuppon'sHub API key is not configured. Please set CUPPONSHUB_API_KEY in Railway.")
        headers = {
            "X-API-Key": self.api_key,
            "User-Agent": "PrimeHubBot/3.0",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _request(
        self,
        method: str,
        action: str,
        *,
        payload: dict[str, Any] | None = None,
        extra_query: dict[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> Any:
        url = f"{self.base_url}/?action={action}"
        if extra_query:
            from urllib.parse import urlencode
            url += f"&{urlencode(extra_query)}"

        headers = self._headers(idempotency_key=idempotency_key)
        if payload is not None:
            headers["Content-Type"] = "application/json"

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    json=payload,
                ) as response:
                    raw = await response.text()
                    try:
                        data = json.loads(raw) if raw else {}
                    except json.JSONDecodeError:
                        data = {"detail": raw or f"HTTP {response.status}"}

                    if response.status >= 400:
                        err_code = data.get("error") or data.get("detail") or data.get("message") or f"HTTP {response.status}"
                        raise CupponsHubError(f"Cuppon'sHub Error: {err_code}")

                    if isinstance(data, dict) and not data.get("ok", True):
                        err_code = data.get("error") or "Unknown API error"
                        raise CupponsHubError(f"Cuppon'sHub Error: {err_code}")

                    return data
        except CupponsHubError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise CupponsHubError(f"Cuppon'sHub connection error: {exc}") from exc

    async def get_balance(self) -> float:
        """Fetch live USDT wallet balance on Cuppon'sHub."""
        if not self.is_configured():
            return 0.0
        data = await self._request("GET", "balance")
        bal_str = str(data.get("balance_usdt", "0"))
        try:
            return float(bal_str)
        except (ValueError, TypeError):
            return 0.0

    async def get_products(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Fetch live catalog and stock from Cuppon'sHub with caching."""
        if not self.is_configured():
            return []

        cache_ttl = getattr(settings, "CUPPONSHUB_CACHE_SECONDS", 60)
        now = time.time()

        if not force_refresh and self._cached_products and (now - self._cache_time) < cache_ttl:
            return self._cached_products

        async with self._lock:
            if not force_refresh and self._cached_products and (time.time() - self._cache_time) < cache_ttl:
                return self._cached_products

            try:
                data = await self._request("GET", "products")
                prods = data.get("products") or []
                if isinstance(prods, list):
                    self._cached_products = prods
                    self._cache_time = time.time()
                    self._update_stock_map()
            except Exception as exc:
                logger.warning(f"Failed to fetch Cuppon'sHub products ({exc}), using cached snapshot if available.")
                if not self._cached_products:
                    return []

            return self._cached_products

    def _update_stock_map(self) -> None:
        new_map: dict[str, int] = {}
        for p in self._cached_products:
            if isinstance(p, dict):
                k = str(p.get("key") or "").strip()
                if k:
                    try:
                        raw_stock = p.get("stock")
                        new_map[k] = 0 if raw_stock is None else max(0, int(raw_stock))
                    except (ValueError, TypeError):
                        new_map[k] = 0
        self._stock_map = new_map

    async def get_all_stock_map(self, force_refresh: bool = False) -> dict[str, int]:
        """Returns pre-computed dictionary of {product_key: stock}."""
        if not self.is_configured():
            return {}
        cache_ttl = getattr(settings, "CUPPONSHUB_CACHE_SECONDS", 60)
        now = time.time()
        if force_refresh or not self._stock_map or (now - self._cache_time) >= cache_ttl:
            await self.get_products(force_refresh=force_refresh)
        return self._stock_map

    async def get_stock(self, product_key: str, force_refresh: bool = False) -> int:
        """Get live available stock for a specific Cuppon'sHub product key."""
        stock_map = await self.get_all_stock_map(force_refresh=force_refresh)
        return stock_map.get(str(product_key).strip(), 0)

    async def create_order(
        self,
        product_key: str,
        quantity: int = 1,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Purchase stock items instantly via Cuppon'sHub Reseller API."""
        quantity = max(1, int(quantity))
        idem = idempotency_key or f"primehub_{uuid.uuid4().hex[:16]}"
        payload = {
            "product": str(product_key).strip(),
            "quantity": quantity,
        }
        data = await self._request(
            "POST",
            "purchase",
            payload=payload,
            idempotency_key=idem,
        )
        order_data = data.get("order") if isinstance(data, dict) else None
        if not isinstance(order_data, dict):
            raise CupponsHubError(f"Unexpected response format from Cuppon'sHub order creation: {data}")
        return order_data

    async def get_order(self, order_id: str) -> dict[str, Any]:
        """Retrieve existing order details and delivered items."""
        data = await self._request("GET", "order", extra_query={"order_id": str(order_id).strip()})
        order_data = data.get("order") if isinstance(data, dict) else None
        if not isinstance(order_data, dict):
            raise CupponsHubError(f"Unexpected response from Cuppon'sHub get_order: {data}")
        return order_data


cupponshub_client = CupponsHubClient()
