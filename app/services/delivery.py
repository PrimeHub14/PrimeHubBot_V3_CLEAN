from html import escape

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order
from app.config import settings
from app.db.repo import (
    allocate_stock_items,
    complete_stock_items,
    mark_delivered,
    release_stock_items,
)


def render_delivery_note(order: Order) -> str:
    note = (order.product.delivery_note or "").strip()
    if not note:
        return ""
    replacements = {
        "{product_name}": order.product.name,
        "{quantity}": str(order.quantity or 1),
        "{order_id}": str(order.id),
        "{support_username}": settings.SUPPORT_USERNAME or "support",
    }
    for key, value in replacements.items():
        note = note.replace(key, value)
    return escape(note)


def note_block(order: Order) -> str:
    note = render_delivery_note(order)
    if not note:
        return ""
    return f"\n\n━━━━━━━━━━━━━━\n\n📘 <b>Important instructions</b>\n{note}"


async def deliver_order(bot: Bot, session: AsyncSession, order: Order) -> None:
    if order.delivered:
        return

    product = order.product

    if product.stock_enabled:
        items = await allocate_stock_items(session, order)
        if len(items) != max(1, order.quantity or 1):
            raise RuntimeError("Not enough stock is available for this order. Add stock before retrying delivery.")
        try:
            text_items = []
            for index, item in enumerate(items, start=1):
                if item.is_file_id:
                    await bot.send_document(
                        order.user_id,
                        item.content,
                        caption=f"✅ Payment confirmed!\n\n📦 {product.name}\nItem {index} of {len(items)}",
                    )
                else:
                    text_items.append(f"<b>Item {index}</b>\n<code>{escape(item.content)}</code>")

            if text_items:
                await bot.send_message(
                    order.user_id,
                    (
                        f"✅ <b>Payment confirmed!</b>\n\n"
                        f"📦 <b>{escape(product.name)}</b>\n"
                        f"🔢 Quantity: <b>{len(items)}</b>\n\n"
                        + "\n\n━━━━━━━━━━━━━━\n\n".join(text_items)
                        + note_block(order)
                        + "\n\n💛 Thank you for choosing us."
                    ),
                    parse_mode="HTML",
                )
            if not text_items and render_delivery_note(order):
                await bot.send_message(
                    order.user_id,
                    f"📘 <b>Important instructions</b>\n{render_delivery_note(order)}",
                    parse_mode="HTML",
                )
            await complete_stock_items(session, order.id)
        except Exception:
            await release_stock_items(session, order.id)
            raise
    elif product.is_file_id:
        await bot.send_document(
            order.user_id,
            product.delivery,
            caption=(
                f"✅ Payment confirmed!\n\n"
                f"📦 {product.name}\n🔢 Quantity: {order.quantity or 1}\n\n"
                f"Thank you for shopping with us. 💛"
            ),
        )
        if render_delivery_note(order):
            await bot.send_message(
                order.user_id,
                f"📘 <b>Important instructions</b>\n{render_delivery_note(order)}",
                parse_mode="HTML",
            )
    else:
        await bot.send_message(
            order.user_id,
            (
                f"✅ <b>Payment confirmed!</b>\n\n"
                f"📦 <b>{escape(product.name)}</b>\n🔢 Quantity: <b>{order.quantity or 1}</b>\n\n"
                f"<code>{escape(product.delivery)}</code>"
                f"{note_block(order)}\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"💛 Thank you for choosing us.\n"
                f"⭐ Enjoy your product!\n"
                f"💬 Need help? Contact support anytime."
            ),
            parse_mode="HTML",
        )

    await mark_delivered(session, order)
