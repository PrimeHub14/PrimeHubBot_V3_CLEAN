import asyncio
from html import escape

from aiogram import Bot

from app.db.session import SessionLocal
from app.db import repo


def payment_window_minutes(order) -> int:
    """Return the user-facing payment window for the order."""
    if order.payment_method in {"usdttrc20_direct", "usdtbep20_direct"}:
        return 30
    return 10


def expiry_label(order) -> str:
    if order.payment_method == "usdttrc20_direct":
        return "USDT TRC20"
    if order.payment_method == "usdtbep20_direct":
        return "USDT BEP20"
    if order.payment_method == "binance":
        return "Binance Pay"
    if order.payment_method == "upi":
        return "UPI"
    if order.payment_method == "wallet":
        return "Wallet"
    return "payment"


async def order_expiry_worker(bot: Bot) -> None:
    while True:
        try:
            async with SessionLocal() as session:
                expired = await repo.expire_unpaid_orders(session)

            for order in expired:
                minutes = payment_window_minutes(order)
                method = expiry_label(order)

                notice = (
                    f"⌛ Order #{order.id} expired after its {minutes}-minute "
                    f"{method} payment window. No inventory was deducted. "
                    "Please create a new order."
                )

                try:
                    await bot.send_message(order.user_id, notice)

                    if (
                        order.payment_message_chat_id
                        and order.payment_message_id
                        and order.payment_message_text
                    ):
                        text = (
                            order.payment_message_text
                            + f"\n\n⌛ <b>EXPIRED after {minutes} minutes — "
                              "please create a new order.</b>"
                        )

                        try:
                            await bot.edit_message_caption(
                                chat_id=order.payment_message_chat_id,
                                message_id=order.payment_message_id,
                                caption=text,
                                parse_mode="HTML",
                                reply_markup=None,
                            )
                        except Exception:
                            try:
                                await bot.edit_message_text(
                                    chat_id=order.payment_message_chat_id,
                                    message_id=order.payment_message_id,
                                    text=text,
                                    parse_mode="HTML",
                                    reply_markup=None,
                                )
                            except Exception:
                                pass
                except Exception:
                    pass
        except Exception:
            pass

        await asyncio.sleep(10)
