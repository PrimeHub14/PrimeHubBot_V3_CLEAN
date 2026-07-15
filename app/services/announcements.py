import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)


async def send_to_update_chats(bot: Bot, text: str, reply_markup=None) -> tuple[int, int]:
    sent = 0
    failed = 0
    for chat_id in settings.update_chat_ids():
        try:
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=reply_markup)
            sent += 1
        except Exception:
            logger.exception("Could not send update to chat %s", chat_id)
            failed += 1
    return sent, failed


async def notify_restock(bot: Bot, product, added: int, available: int) -> tuple[int, int]:
    text = (
        "🔔 <b>Stock Updated</b>\n\n"
        f"📦 <b>{product.name}</b>\n"
        f"➕ Added: <b>{added}</b>\n"
        f"✅ Available now: <b>{available}</b>\n"
        f"💵 Price: <b>${float(product.price):.2f}</b>"
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛍 View Product", callback_data=f"product:{product.id}")]
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
            logger.info("Could not notify subscriber %s", user_id)

    group_sent, _ = await send_to_update_chats(bot, text, reply_markup=markup)
    return user_sent, group_sent
