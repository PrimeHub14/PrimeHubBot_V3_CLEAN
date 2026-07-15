import asyncio
from datetime import datetime, timezone
from html import escape

from aiogram import Bot
from app.db.session import SessionLocal
from app.db import repo


async def order_expiry_worker(bot: Bot) -> None:
    while True:
        try:
            async with SessionLocal() as session:
                expired = await repo.expire_unpaid_orders(session)
            for order in expired:
                try:
                    await bot.send_message(order.user_id, f"⌛ Order #{order.id} expired after its full 10-minute payment window. Reserved stock was released. Please create a new order.")
                    if order.payment_message_chat_id and order.payment_message_id and order.payment_message_text:
                        text = order.payment_message_text + "\n\n⌛ <b>EXPIRED — please create a new order.</b>"
                        try:
                            await bot.edit_message_caption(chat_id=order.payment_message_chat_id, message_id=order.payment_message_id, caption=text, parse_mode="HTML", reply_markup=None)
                        except Exception:
                            try:
                                await bot.edit_message_text(chat_id=order.payment_message_chat_id, message_id=order.payment_message_id, text=text, parse_mode="HTML", reply_markup=None)
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass
        await asyncio.sleep(15)
