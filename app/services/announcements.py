from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


async def send_to_update_chats(bot: Bot, text: str, reply_markup=None) -> tuple[int, int]:
    """Send message to all configured announcement channels and groups."""
    sent = 0
    failed = 0
    chat_targets = settings.update_chat_ids() if callable(settings.update_chat_ids) else settings.update_chat_ids
    for chat_id in chat_targets:
        try:
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
            sent += 1
        except Exception:
            logger.exception("Could not send update to chat %s", chat_id)
            failed += 1
    return sent, failed


async def notify_restock(bot: Bot, product, added: int, available: int) -> tuple[int, int]:
    """Notify subscribers, announcement channels/groups, and admins of newly available stock.
    
    Produces strictly the clean card requested by the user:
    - No supplier names
    - No internal debug text
    - Direct [🛍 View Product] button
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
    notified_user_ids: set[int] = set()
    for user_id in subscribers:
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=markup)
            user_sent += 1
            notified_user_ids.add(user_id)
        except Exception:
            logger.info("Could not notify subscriber %s for product #%s", user_id, product.id)

    # Broadcast to channels and groups
    group_sent, _ = await send_to_update_chats(bot, text, reply_markup=markup)

    # Deliver clean card to admins
    for admin_id in settings.admin_ids:
        if admin_id not in notified_user_ids:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=markup)
            except Exception:
                pass

    return user_sent, group_sent


async def notify_new_product(
    bot: Bot,
    product,
    available: int = 0,
    broadcast_users: bool = False,
) -> tuple[int, int]:
    """Notify announcement channels, admins, and optionally bot users of a newly added product.
    
    Produces strictly the clean card requested by the user:
    - No supplier names
    - No internal debug text
    - Direct [🛍 View Product] button
    """
    safe_name = escape(product.name or "")
    if available > 0:
        avail_str = f"<b>{available}</b>"
    elif getattr(product, "delivery_mode", "instant") == "manual":
        avail_str = "<b>Ready / Instant Delivery</b>"
    else:
        avail_str = "<b>In Stock</b>"

    text = (
        "🎉 <b>New Product Added!</b>\n\n"
        f"📦 <b>{safe_name}</b>\n"
        f"✅ Available Now: {avail_str}\n"
        f"💵 Price: <b>${float(product.price):.2f}</b>\n\n"
        "⚡ <i>Instant automated delivery is ready! Tap below to order:</i>"
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛍 View Product", callback_data=f"product:{product.id}")],
        ]
    )

    user_sent = 0
    if broadcast_users:
        async with SessionLocal() as session:
            all_uids = await repo.audience_user_ids(session, "all")
        for uid in all_uids:
            try:
                await bot.send_message(uid, text, parse_mode="HTML", reply_markup=markup)
                user_sent += 1
            except Exception:
                pass
            await asyncio.sleep(0.035)

    # Broadcast to channels and groups
    group_sent, _ = await send_to_update_chats(bot, text, reply_markup=markup)

    # Deliver clean card to admins
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass

    return user_sent, group_sent
