from __future__ import annotations

import asyncio
import logging
from html import escape
from typing import Any

from aiogram import Bot

from app.config import settings
from app.db import repo
from app.db.models import Product
from app.db.session import SessionLocal
from app.services.announcements import notify_restock
from app.services.loot_paglu import (
    is_paglu_enabled,
    is_paglu_product,
    get_paglu_service_id_for_product,
    loot_paglu_client,
)
from app.services.ventebot import (
    ventebot_client,
    get_ventebot_target_id,
    get_effective_product_stock,
)

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS: int = 900  # 15 minutes as requested
_last_known_stock: dict[str, int] = {}
_initialized: bool = False


async def notify_subscribers_supplier_restock(
    bot: Bot,
    product: Product,
    added: int,
    available: int,
    supplier_name: str = "",
) -> int:
    """Notify subscribers, announcement channels/groups, and admins of fresh stock.

    Produces strictly the clean card requested by the user:
    - Zero supplier info
    - No internal debug summaries
    - Direct [🛍 View Product] button
    """
    user_sent, _ = await notify_restock(bot, product, added, available)
    return user_sent


async def check_supplier_restocks(bot: Bot) -> list[str]:
    """Check both Paglu and VenteBot for newly added stock and trigger alerts."""
    global _last_known_stock, _initialized
    report = []

    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=True)

    # 1. Check Paglu linked products
    if is_paglu_enabled() and loot_paglu_client.is_configured():
        for p in products:
            if not is_paglu_product(p.id, p):
                continue
            sid = get_paglu_service_id_for_product(p.id, p)
            if not sid:
                continue

            try:
                curr_stock = await loot_paglu_client.stock(sid, force_refresh=True)
            except Exception as exc:
                logger.warning(f"Restock check error for service {sid}: {exc}")
                continue

            key = f"paglu_{p.id}_{sid}"
            if _initialized and key in _last_known_stock:
                prev_stock = _last_known_stock[key]
                if curr_stock > prev_stock and curr_stock > 0:
                    added = curr_stock - prev_stock
                    async with SessionLocal() as session:
                        total_available = await get_effective_product_stock(session, p, force_refresh=False)
                    notified = await notify_subscribers_supplier_restock(
                        bot, p, added, total_available
                    )
                    msg = f"Stock added +{added} for #{p.id} {p.name} (notified {notified} users)"
                    report.append(msg)
                    logger.info(msg)

            _last_known_stock[key] = curr_stock

    # 2. Check VenteBot linked products
    if ventebot_client.is_configured():
        for p in products:
            v_id = get_ventebot_target_id(p)
            if not v_id:
                continue

            try:
                curr_stock = await ventebot_client.get_stock(v_id, force_refresh=True)
            except Exception as exc:
                logger.warning(f"Restock check error for product {v_id}: {exc}")
                continue

            key = f"vente_{p.id}_{v_id}"
            if _initialized and key in _last_known_stock:
                prev_stock = _last_known_stock[key]
                if curr_stock > prev_stock and curr_stock > 0:
                    added = curr_stock - prev_stock
                    async with SessionLocal() as session:
                        total_available = await get_effective_product_stock(session, p, force_refresh=False)
                    notified = await notify_subscribers_supplier_restock(
                        bot, p, added, total_available
                    )
                    msg = f"Stock added +{added} for #{p.id} {p.name} (notified {notified} users)"
                    report.append(msg)
                    logger.info(msg)

            _last_known_stock[key] = curr_stock

    _initialized = True
    return report


async def supplier_restock_monitor_loop(bot: Bot) -> None:
    """Background task that checks supplier restocks every 15 minutes."""
    logger.info("Stock monitor loop started (15-minute polling interval).")
    await asyncio.sleep(15)
    try:
        await check_supplier_restocks(bot)
    except Exception as exc:
        logger.warning(f"Initial stock baseline capture failed: {exc}")

    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            await check_supplier_restocks(bot)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception("Error in stock monitor loop: %s", exc)
            await asyncio.sleep(60)
