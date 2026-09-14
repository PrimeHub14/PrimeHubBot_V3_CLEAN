import asyncio
import json
import logging
import time
import uuid
from typing import Any

import aiohttp
from sqlalchemy import select

from app.config import settings
from app.db.models import Product

logger = logging.getLogger(__name__)


class VenteBotError(RuntimeError):
    pass


def is_ventebot_product(product) -> bool:
    if not product:
        return False
    if getattr(product, "ventebot_product_id", None):
        return True
    v_prod_id = getattr(settings, "VENTEBOT_PRODUCT_ID", 0)
    if v_prod_id and int(product.id) == int(v_prod_id):
        return True
    return False


def get_ventebot_target_id(product) -> int | None:
    if not product:
        return None
    if getattr(product, "ventebot_product_id", None):
        return int(product.ventebot_product_id)
    v_prod_id = getattr(settings, "VENTEBOT_PRODUCT_ID", 0)
    v_serv_id = getattr(settings, "VENTEBOT_SERVICE_ID", 0)
    if v_prod_id and int(product.id) == int(v_prod_id) and v_serv_id:
        return int(v_serv_id)
    return None


class VenteBotClient:
    def __init__(self) -> None:
        self.base_url = (getattr(settings, "VENTEBOT_BASE_URL", "") or "https://ventetelegrambotrailway-production.up.railway.app").rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=getattr(settings, "VENTEBOT_TIMEOUT_SECONDS", 15))
        self._cached_products: list[dict[str, Any]] = []
        self._cache_time: float = 0.0
        self._etag: str = ""
        self._stock_map: dict[int, int] = {}
        self._lock = asyncio.Lock()

    @property
    def api_key(self) -> str:
        return (getattr(settings, "VENTEBOT_API_KEY", "") or "").strip()

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self, bypass_etag: bool = False) -> dict[str, str]:
        if not self.api_key:
            raise VenteBotError("VenteBot Reseller API key is not configured. Please set VENTEBOT_API_KEY in Railway.")
        headers = {
            "X-Reseller-Key": self.api_key,
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": "PrimeHubBot/3.0",
        }
        if self._etag and not bypass_etag:
            headers["If-None-Match"] = self._etag
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        bypass_etag: bool = False,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.request(
                    method,
                    url,
                    headers=self._headers(bypass_etag=bypass_etag),
                    json=payload,
                ) as response:
                    if response.status == 304:
                        self._cache_time = time.time()
                        return self._cached_products

                    raw = await response.text()
                    try:
                        data = json.loads(raw) if raw else {}
                    except json.JSONDecodeError:
                        data = {"detail": raw or f"HTTP {response.status}"}

                    if response.status >= 400:
                        detail = data.get("detail") or data.get("message") or data.get("error") or f"HTTP {response.status}"
                        raise VenteBotError(str(detail))

                    new_etag = response.headers.get("ETag")
                    if new_etag:
                        self._etag = new_etag

                    return data
        except VenteBotError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise VenteBotError(f"VenteBot API connection error: {exc}") from exc

    async def me(self) -> dict[str, Any]:
        """Fetch reseller account profile and live USD wallet balance."""
        return await self._request("GET", "/api/reseller/me")

    async def get_products(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        """Fetch all products with live stock from VenteBot (cached for TTL seconds)."""
        if not self.is_configured():
            return []

        cache_ttl = getattr(settings, "VENTEBOT_CACHE_SECONDS", 60)
        now = time.time()

        if not force_refresh and self._cached_products and (now - self._cache_time) < cache_ttl:
            return self._cached_products

        async with self._lock:
            if not force_refresh and self._cached_products and (time.time() - self._cache_time) < cache_ttl:
                return self._cached_products

            try:
                data = await self._request("GET", "/api/reseller/products", bypass_etag=force_refresh)
                if data is not None and isinstance(data, list):
                    self._cached_products = data
                    self._cache_time = time.time()
                elif data is not None and isinstance(data, dict):
                    products = data.get("products") or data.get("items") or []
                    if isinstance(products, list):
                        self._cached_products = products
                        self._cache_time = time.time()
                self._update_stock_map()
            except Exception as exc:
                logger.warning(f"Failed to fetch VenteBot products ({exc}), using cached snapshot if available.")
                if not self._cached_products:
                    return []

            return self._cached_products

    def _update_stock_map(self) -> None:
        new_map: dict[int, int] = {}
        for p in self._cached_products:
            if isinstance(p, dict):
                v_id = int(p.get("id") or 0)
                if v_id > 0:
                    stock = p.get("stock")
                    new_map[v_id] = 999 if stock is None else max(0, int(stock))
        self._stock_map = new_map

    async def get_all_stock_map(self, force_refresh: bool = False) -> dict[int, int]:
        """Returns a fast pre-computed dictionary of {ventebot_product_id: stock} in 0ms."""
        if not self.is_configured():
            return {}
        cache_ttl = getattr(settings, "VENTEBOT_CACHE_SECONDS", 60)
        now = time.time()
        if force_refresh or not self._stock_map or (now - self._cache_time) >= cache_ttl:
            await self.get_products(force_refresh=force_refresh)
        return self._stock_map

    async def get_stock(self, ventebot_product_id: int, force_refresh: bool = False) -> int:
        """Get live stock count for a specific VenteBot product."""
        stock_map = await self.get_all_stock_map(force_refresh=force_refresh)
        return stock_map.get(int(ventebot_product_id), 0)

    async def create_order(
        self,
        ventebot_product_id: int,
        quantity: int = 1,
        customer_reference: str = "",
        activation_identifier: str | None = None,
    ) -> dict[str, Any]:
        """Place an order with VenteBot to purchase and receive delivery items instantly."""
        quantity = max(1, int(quantity))
        payload: dict[str, Any] = {
            "product_id": int(ventebot_product_id),
            "quantity": quantity,
            "idempotency_key": f"primehub_{uuid.uuid4().hex[:16]}",
        }
        if customer_reference:
            payload["customer_reference"] = str(customer_reference)[:120]
        if activation_identifier:
            payload["activation_identifier"] = str(activation_identifier)[:500]

        data = await self._request("POST", "/api/reseller/orders", payload=payload)
        if not isinstance(data, dict):
            raise VenteBotError("Unexpected response format from VenteBot order creation")
        return data


ventebot_client = VenteBotClient()


async def get_effective_product_stock(session, product, force_refresh: bool = False) -> int:
    """Unified stock calculator for all product types (Local, VenteBot, LootPaglu, Manual)."""
    if not product:
        return 0

    # 1. VenteBot Reseller API product
    v_id = get_ventebot_target_id(product)
    if v_id:
        try:
            if ventebot_client.is_configured():
                return await ventebot_client.get_stock(v_id, force_refresh=force_refresh)
        except Exception as exc:
            logger.warning(f"Error fetching VenteBot live stock for #{product.id}: {exc}")
            return 0

    # 2. LootPaglu mapped product
    try:
        from app.services.loot_paglu import is_paglu_product, live_stock
        if is_paglu_product(product.id):
            return await live_stock(product.id, 0)
    except Exception:
        pass

    # 3. Non-stock enabled or manual delivery items
    if not getattr(product, "stock_enabled", True) or getattr(product, "delivery_mode", "instant") == "manual":
        return 999

    # 3. Local inventory from database
    try:
        from app.db import repo
        local = await repo.available_stock_count(session, product.id)
        return max(0, int(local))
    except Exception as exc:
        logger.warning(f"Error getting local stock count for #{product.id}: {exc}")
        return 0