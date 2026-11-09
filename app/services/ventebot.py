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
        self._base_url_override: str | None = None
        self._api_key_override: str | None = None
        self.timeout = aiohttp.ClientTimeout(total=getattr(settings, "VENTEBOT_TIMEOUT_SECONDS", 15))
        self._cached_products: list[dict[str, Any]] = []
        self._cache_time: float = 0.0
        self._etag: str = ""
        self._stock_map: dict[int, int] = {}
        self._lock = asyncio.Lock()
        self._last_error: str = ""

    @property
    def base_url(self) -> str:
        url = self._base_url_override or getattr(settings, "VENTEBOT_BASE_URL", "") or "https://ventetelegrambotrailway-production.up.railway.app"
        return url.rstrip("/")

    def set_base_url(self, url: str) -> None:
        self._base_url_override = str(url).strip().rstrip("/")
        self._cached_products = []
        self._cache_time = 0.0

    @property
    def api_key(self) -> str:
        key = self._api_key_override or getattr(settings, "VENTEBOT_API_KEY", "") or ""
        return key.strip()

    def set_api_key(self, key: str) -> None:
        self._api_key_override = str(key).strip()

    @property
    def last_error(self) -> str:
        return self._last_error

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self, bypass_etag: bool = False) -> dict[str, str]:
        if not self.api_key:
            raise VenteBotError("VenteBot Reseller API key is not configured. Please set VENTEBOT_API_KEY in Railway or via /ventesetkey.")
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
                        err_msg = f"{detail} (HTTP {response.status} at {url})"
                        self._last_error = err_msg
                        raise VenteBotError(err_msg)

                    new_etag = response.headers.get("ETag")
                    if new_etag:
                        self._etag = new_etag

                    self._last_error = ""
                    return data
        except VenteBotError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            err_msg = f"VenteBot API connection error: {exc} (at {url})"
            self._last_error = err_msg
            raise VenteBotError(err_msg) from exc

    async def me(self) -> dict[str, Any]:
        """Fetch reseller account profile and live USD wallet balance."""
        return await self._request("GET", "/api/reseller/me")

    async def get_products(self, force_refresh: bool = False, raise_for_error: bool = False) -> list[dict[str, Any]]:
        """Fetch all products with live stock from VenteBot (cached for TTL seconds)."""
        if not self.is_configured():
            if raise_for_error:
                raise VenteBotError("VenteBot API key is not configured. Set VENTEBOT_API_KEY in Railway or via /ventesetkey.")
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
                self._last_error = ""
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning(f"Failed to fetch VenteBot products ({exc}), using cached snapshot if available.")
                if raise_for_error:
                    raise
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

    async def get_order(self, order_id: int) -> dict[str, Any]:
        """Fetch live status and delivery items for an existing VenteBot order."""
        data = await self._request("GET", f"/api/reseller/orders/{int(order_id)}")
        if not isinstance(data, dict):
            raise VenteBotError("Unexpected response format from VenteBot get_order")
        return data


ventebot_client = VenteBotClient()


async def get_effective_product_stock(session, product, force_refresh: bool = False) -> int:
    """Unified stock calculator for all product types (Local, Cuppon'sHub, LootPaglu, VenteBot, Reusable)."""
    if not product:
        return 0

    from app.db import repo

    # 1. Check local inventory items in database
    try:
        local_stock = max(0, int(await repo.available_stock_count(session, product.id)))
    except Exception as exc:
        logger.warning(f"Error getting local stock count for #{product.id}: {exc}")
        local_stock = 0

    supplier_stock = 0
    has_supplier = False

    # 2. Cuppon'sHub Reseller API product
    ch_key = getattr(product, "cupponshub_product_id", None)
    if ch_key:
        has_supplier = True
        try:
            from app.services.cupponshub import cupponshub_client
            if cupponshub_client.is_configured():
                supplier_stock = await cupponshub_client.get_stock(str(ch_key).strip(), force_refresh=force_refresh)
        except Exception as exc:
            logger.warning(f"Error fetching Cuppon'sHub live stock for #{product.id}: {exc}")

    # 3. LootPaglu mapped product
    elif getattr(product, "paglu_service_id", None):
        has_supplier = True
        try:
            from app.services.loot_paglu import loot_paglu_client
            sid = str(product.paglu_service_id).strip()
            if loot_paglu_client.is_configured():
                supplier_stock = await loot_paglu_client.stock(sid, force_refresh=force_refresh)
        except Exception as exc:
            logger.warning(f"Error fetching LootPaglu live stock for #{product.id}: {exc}")

    # 4. VenteBot Reseller API product
    else:
        v_id = get_ventebot_target_id(product)
        if v_id:
            has_supplier = True
            try:
                if ventebot_client.is_configured():
                    supplier_stock = await ventebot_client.get_stock(v_id, force_refresh=force_refresh)
            except Exception as exc:
                logger.warning(f"Error fetching VenteBot live stock for #{product.id}: {exc}")

    # If linked to a supplier, total available = local stock + supplier stock
    if has_supplier:
        return local_stock + max(0, int(supplier_stock or 0))

    # If local stock exists, return local stock count
    if local_stock > 0:
        return local_stock

    # Pure Manual or Reusable static delivery item (only when explicitly set with delivery content or manual mode)
    if getattr(product, "delivery_mode", "instant") == "manual":
        return 999
    if not getattr(product, "stock_enabled", True) and bool(getattr(product, "delivery", "") and str(product.delivery).strip()):
        return 999

    # Standard unlinked product with 0 stock items
    return 0