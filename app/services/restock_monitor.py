from __future__ import annotations

import asyncio
import logging
from html import escape
from typing import Any

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.db import repo
from app.db.models import Product
from app.db.session import SessionLocal
from app.services.loot_paglu import (
    is_paglu_enabled,
    is_paglu_product,
    get_paglu_service_id_for_product,
    loot_paglu_client,
)
from app.services.ventebot import ventebot_client, get_ventebot_target_id

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS: int = 900  # 15 minutes as requested
_last_known_stock: dict[str, int] = {}
_initialized: bool = False


async def notify_subscribers_supplier_restock(
    bot: Bot,
    product: Product,
    added: int,
    available: int,
    supplier_name: str = "Supplier",
) -> int:
    """Notify users who subscribed to restock alerts for this product via DM.
    
    Does NOT auto-post to public channels/groups so the admin can post manually.
    Also alerts store admins so they are aware fresh stock has arrived.
    """
    safe_name = escape(product.name or "")
    text = (
        "🔔 <b>New Stock Available!</b>\n\n"
        f"📦 <b>{safe_name}</b>\n"
        f"➕ Fresh Stock Added: <b>+{added} unit(s)</b>\n"
        f"✅ Available Now: <b>{available}</b>\n"
        f"💵 Price: <b>${float(product.price):.2f}</b>\n\n"
        "⚡ <i>Instant automated delivery is ready! Tap below to order:</i>"
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛍 View Product", callback_data=f"product:{product.id}")],
        ]
    )

    async with SessionLocal() as session:
        subscribers = await repo.restock_subscribers(session, product.id)

    user_sent = 0
    for user_id in subscribers:
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=markup)
            user_sent += 1
        except Exception:
            logger.info("Could not notify subscriber %s for product #%s", user_id, product.id)

    # Notify store admins directly so they can manually post to channel/group if desired
    admin_notice = (
        f"🔔 <b>[Supplier Restock Detected]</b>\n\n"
        f"📦 <b>{safe_name}</b> (ID <code>#{product.id}</code>)\n"
        f"🌐 Source: <b>{escape(supplier_name)}</b>\n"
        f"➕ Added: <b>+{added} units</b> | Total Available: <b>{available}</b>\n"
        f"👥 Notified {user_sent} subscriber(s) in bot DM.\n\n"
        f"💡 <i>You can now copy and post this update to your Prime Hub channel manually.</i>"
    )
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, admin_notice, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass

    return user_sent


async def check_supplier_restocks(bot: Bot) -> list[str]:
    """Check both Paglu and VenteBot for newly added stock and trigger alerts."""
    global _last_known_stock, _initialized
    report = []

    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=True)

    # 1. Check Paglu Shop Bot Linked Products
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
                logger.warning(f"Restock check error for Paglu service {sid}: {exc}")
                continue

            key = f"paglu_{p.id}_{sid}"
            if _initialized and key in _last_known_stock:
                prev_stock = _last_known_stock[key]
                if curr_stock > prev_stock and curr_stock > 0:
                    added = curr_stock - prev_stock
                    async with SessionLocal() as session:
                        local_stock = await repo.available_stock_count(session, p.id)
                    total_available = local_stock + curr_stock
                    notified = await notify_subscribers_supplier_restock(
                        bot, p, added, total_available, supplier_name="Paglu Shop Bot"
                    )
                    msg = f"Paglu added +{added} for #{p.id} {p.name} (notified {notified} users)"
                    report.append(msg)
                    logger.info(msg)

            _last_known_stock[key] = curr_stock

    # 2. Check VenteBot Linked Products
    if ventebot_client.is_configured():
        for p in products:
            v_id = get_ventebot_target_id(p)
            if not v_id:
                continue

            try:
                curr_stock = await ventebot_client.get_stock(v_id, force_refresh=True)
            except Exception as exc:
                logger.warning(f"Restock check error for VenteBot ID {v_id}: {exc}")
                continue

            key = f"vente_{p.id}_{v_id}"
            if _initialized and key in _last_known_stock:
                prev_stock = _last_known_stock[key]
                if curr_stock > prev_stock and curr_stock > 0:
                    added = curr_stock - prev_stock
                    notified = await notify_subscribers_supplier_restock(
                        bot, p, added, curr_stock, supplier_name="VenteBot"
                    )
                    msg = f"VenteBot added +{added} for #{p.id} {p.name} (notified {notified} users)"
                    report.append(msg)
                    logger.info(msg)

            _last_known_stock[key] = curr_stock

    _initialized = True
    return report


async def supplier_restock_monitor_loop(bot: Bot) -> None:
    """Background task that checks Paglu and VenteBot every 15 minutes."""
    logger.info("Supplier restock monitor started (15-minute polling interval).")
    # Quick initial baseline capture after bot startup (waits 15 seconds)
    await asyncio.sleep(15)
    try:
        await check_supplier_restocks(bot)
    except Exception as exc:
        logger.warning(f"Initial supplier stock baseline capture failed: {exc}")

    while True:
        try:
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)
            await check_supplier_restocks(bot)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.exception("Error in supplier restock monitor loop: %s", exc)
            await asyncio.sleep(60)
