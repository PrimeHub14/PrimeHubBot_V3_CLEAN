from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.models import Order
from app.db.repo import mark_delivered


async def deliver_order(bot: Bot, session: AsyncSession, order: Order) -> None:
    if order.delivered:
        return

    product = order.product

    if product.is_file_id:
        await bot.send_document(
            order.user_id,
            product.delivery,
            caption=(
                f"✅ Payment confirmed!\n\n"
                f"📦 {product.name}\n\n"
                f"Thank you for shopping with us. 💛"
            ),
        )
    else:
        await bot.send_message(
            order.user_id,
            (
                f"✅ <b>Payment confirmed!</b>\n\n"
                f"📦 <b>{product.name}</b>\n\n"
                f"{product.delivery}\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"💛 Thank you for choosing us.\n"
                f"⭐ Enjoy your product!\n"
                f"💬 Need help? Contact support anytime."
            ),
            parse_mode="HTML",
        )

    await mark_delivered(session, order)
