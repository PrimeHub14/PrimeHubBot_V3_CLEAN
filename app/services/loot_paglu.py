from __future__ import annotations

import json
import logging
import time
from typing import Any

import aiohttp

from app.config import settings

logger = logging.getLogger(__name__)


class LootPagluError(RuntimeError):
    pass


_paglu_enabled: bool = True
_paglu_override_product_id: int | None = None
_paglu_override_service_id: str | None = None
_product_service_map: dict[int, str] = {}


def is_paglu_enabled() -> bool:
    global _paglu_enabled
    return _paglu_enabled and bool(settings.LOOTPAGLU_API_KEY)


def set_paglu_enabled(enabled: bool) -> None:
    global _paglu_enabled
    _paglu_enabled = bool(enabled)


def get_paglu_product_id() -> int:
    global _paglu_override_product_id
    if _paglu_override_product_id is not None:
        return _paglu_override_product_id
    return int(settings.LOOTPAGLU_PRODUCT_ID or 0)


def set_paglu_product_id(product_id: int | None) -> None:
    global _paglu_override_product_id
    _paglu_override_product_id = product_id


def get_paglu_service_id() -> str:
    global _paglu_override_service_id
    if _paglu_override_service_id is not None:
        return _paglu_override_service_id
    return str(settings.LOOTPAGLU_SERVICE_ID or "Paglu_8")


def set_paglu_service_id(service_id: str | None) -> None:
    global _paglu_override_service_id
    _paglu_override_service_id = service_id


def set_product_paglu_service(product_id: int, service_id: str | None) -> None:
    global _product_service_map
    if service_id:
        _product_service_map[int(product_id)] = str(service_id).strip()
    else:
        _product_service_map.pop(int(product_id), None)


def get_paglu_service_id_for_product(product_id: int, product: Any = None) -> str | None:
    if product and getattr(product, "paglu_service_id", None):
        sid = str(product.paglu_service_id).strip()
        if sid.lower() in {"paglu_1", "paglu1"}:
            return "Paglu_8"
        return sid
    if int(product_id) in _product_service_map:
        sid = _product_service_map[int(product_id)]
        if sid.lower() in {"paglu_1", "paglu1"}:
            return "Paglu_8"
        return sid
    target = get_paglu_product_id()
    if target > 0 and int(product_id) == int(target):
        sid = get_paglu_service_id()
        if sid.lower() in {"paglu_1", "paglu1"}:
            return "Paglu_8"
        return sid
    if product and "gemini" in str(getattr(product, "name", "")).lower():
        return "Paglu_8"
    return None


def is_paglu_product(product_id: int, product: Any = None) -> bool:
    if not is_paglu_enabled():
        return False
    return get_paglu_service_id_for_product(product_id, product) is not None


class LootPagluClient:
    def __init__(self) -> None:
        self.base_url = (getattr(settings, "LOOTPAGLU_BASE_URL", "") or "https://lootpaglu.in").rstrip("/")
        self.api_key = (getattr(settings, "LOOTPAGLU_API_KEY", "") or "").strip()
        self.timeout = aiohttp.ClientTimeout(total=max(5, settings.LOOTPAGLU_TIMEOUT_SECONDS))
        self._cached_products: list[dict[str, Any]] = []
        self._cache_time: float = 0.0
        self._cache_ttl: float = 20.0

    def is_configured(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise LootPagluError("Loot Paglu API key is not configured")
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "ngrok-skip-browser-warning": "true",
        }

    async def _request(self, method: str, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.base_url:
            raise LootPagluError("Loot Paglu API base URL is not configured")
        url = f"{self.base_url}{path}"
        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.request(method, url, headers=self._headers(), json=payload) as response:
                    raw = await response.text()
                    try:
                        data = json.loads(raw) if raw else {}
                    except json.JSONDecodeError:
                        data = {"error": raw or f"HTTP {response.status}"}
                    if response.status >= 400:
                        message = data.get("error") or data.get("message") or f"HTTP {response.status}"
                        raise LootPagluError(str(message))
                    return data
        except LootPagluError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            raise LootPagluError(f"Loot Paglu API connection error: {exc}") from exc

    async def me(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/me")

    async def products(self, force_refresh: bool = False) -> list[dict[str, Any]]:
        if not force_refresh and (time.time() - self._cache_time < self._cache_ttl) and self._cached_products:
            return self._cached_products
        try:
            data = await self._request("GET", "/api/v1/products")
            items = []
            if isinstance(data, list):
                items = [x for x in data if isinstance(x, dict)]
            elif isinstance(data, dict):
                services = data.get("services") or data.get("products") or []
                if isinstance(services, list):
                    items = [x for x in services if isinstance(x, dict)]
            if items:
                self._cached_products = items
                self._cache_time = time.time()
                return items
            return self._cached_products
        except Exception as exc:
            logger.warning(f"LootPaglu products request failed: {exc}")
            return self._cached_products

    async def service(self, service_id: str | None = None, force_refresh: bool = False) -> dict[str, Any] | None:
        raw_wanted = (service_id or get_paglu_service_id()).strip().lower()
        wanted = "paglu_8" if raw_wanted in {"paglu_1", "paglu1"} else raw_wanted
        services = await self.products(force_refresh=force_refresh)
        for service in services:
            if not isinstance(service, dict):
                continue
            s_id = str(service.get("service_id") or "").strip().lower()
            s_name = str(service.get("name") or "").strip().lower()
            if s_id == wanted or (wanted not in {"paglu_8"} and wanted in s_name):
                return service
        # Fallback: if looking for Paglu_8 or Gemini, find the active in-stock Gemini service
        if wanted == "paglu_8" or "gemini" in wanted:
            for service in services:
                if not isinstance(service, dict):
                    continue
                s_id = str(service.get("service_id") or "").strip().lower()
                s_name = str(service.get("name") or "").strip().lower()
                if "gemini" in s_name and (s_id == "paglu_8" or int(service.get("available_stock", 0)) > 0):
                    return service
        return None

    async def stock(self, service_id: str | None = None, force_refresh: bool = False) -> int:
        service = await self.service(service_id or get_paglu_service_id(), force_refresh=force_refresh)
        if not service or not isinstance(service, dict):
            return 0
        try:
            return max(0, int(service.get("available_stock") or 0))
        except (TypeError, ValueError):
            return 0

    async def order(self, quantity: int, service_id: str | None = None) -> dict[str, Any]:
        quantity = max(1, int(quantity))
        raw_target = (service_id or get_paglu_service_id()).strip()
        target_service = "Paglu_8" if raw_target.lower() in {"paglu_1", "paglu1"} else raw_target
        payload = {
            "service_id": target_service,
            "quantity": quantity,
            "currency": settings.LOOTPAGLU_CURRENCY.strip().lower() or "inr",
        }
        data = await self._request("POST", "/api/v1/order", payload=payload)
        if data.get("success") is False or data.get("status") == "error":
            raise LootPagluError(str(data.get("error") or data.get("message") or "Supplier order failed"))
        products = data.get("products")
        if not isinstance(products, list) or len(products) < quantity:
            raise LootPagluError("Supplier order completed but did not return the expected delivery items")
        # Invalidate cache so stock is re-read on next check
        self._cache_time = 0.0
        return data


loot_paglu_client = LootPagluClient()


async def live_stock(
    product_id: int,
    local_stock: int | None = None,
    product: Any = None,
    service_id: str | None = None,
) -> int:
    """Return combined stock: own local stock + Paglu supplier stock when linked."""
    local = max(0, int(local_stock or 0))
    if not is_paglu_enabled():
        return local
    sid = service_id or get_paglu_service_id_for_product(product_id, product)
    if not sid:
        return local
    try:
        supplier = await loot_paglu_client.stock(sid)
        return local + supplier
    except Exception as exc:
        logger.warning(f"Failed to fetch live stock for product {product_id} ({sid}): {exc}")
        return local
