import json
from typing import Any

import aiohttp

from app.config import settings


class LootPagluError(RuntimeError):
    pass


def is_paglu_product(product_id: int) -> bool:
    return bool(
        settings.LOOTPAGLU_API_KEY
        and settings.LOOTPAGLU_PRODUCT_ID > 0
        and int(product_id) == int(settings.LOOTPAGLU_PRODUCT_ID)
    )


class LootPagluClient:
    def __init__(self) -> None:
        self.base_url = settings.LOOTPAGLU_BASE_URL.rstrip("/")
        self.api_key = settings.LOOTPAGLU_API_KEY.strip()
        self.timeout = aiohttp.ClientTimeout(total=max(5, settings.LOOTPAGLU_TIMEOUT_SECONDS))

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

    async def products(self) -> list[dict[str, Any]]:
        data = await self._request("GET", "/api/v1/products")
        services = data.get("services") or []
        return services if isinstance(services, list) else []

    async def service(self, service_id: str | None = None) -> dict[str, Any] | None:
        wanted = (service_id or settings.LOOTPAGLU_SERVICE_ID).strip()
        for service in await self.products():
            if str(service.get("service_id")) == wanted:
                return service
        return None

    async def stock(self, service_id: str | None = None) -> int:
        service = await self.service(service_id)
        if not service:
            return 0
        try:
            return max(0, int(service.get("available_stock") or 0))
        except (TypeError, ValueError):
            return 0

    async def order(self, quantity: int, service_id: str | None = None) -> dict[str, Any]:
        quantity = max(1, int(quantity))
        payload = {
            "service_id": (service_id or settings.LOOTPAGLU_SERVICE_ID).strip(),
            "quantity": quantity,
            "currency": settings.LOOTPAGLU_CURRENCY.strip().lower() or "inr",
        }
        data = await self._request("POST", "/api/v1/order", payload=payload)
        if data.get("success") is False or data.get("status") == "error":
            raise LootPagluError(str(data.get("error") or data.get("message") or "Supplier order failed"))
        products = data.get("products")
        if not isinstance(products, list) or len(products) < quantity:
            raise LootPagluError("Supplier order completed but did not return the expected delivery items")
        return data


async def live_stock(product_id: int, local_stock: int | None = None) -> int:
    """Return supplier stock for the mapped Gemini product; local stock for everything else."""
    if not is_paglu_product(product_id):
        return max(0, int(local_stock or 0))
    try:
        return await LootPagluClient().stock()
    except LootPagluError:
        # Fail closed: never sell API stock when the supplier cannot be checked.
        return 0
