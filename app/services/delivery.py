from html import escape
from datetime import timezone

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


def delivery_timestamp(order: Order) -> str:
    value = getattr(order, "created_at", None)
    if not value:
        return "Unknown"
    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    except Exception:
        return str(value)


def delivery_header(order: Order) -> str:
    return (
        "✅ <b>Order Delivered</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"🧾 Order ID: <b>#{order.id}</b>\n"
        f"📦 Product: <b>{escape(order.product.name)}</b>\n"
        f"🔢 Quantity: <b>{order.quantity or 1}</b>\n"
        f"🕒 Date & Time: <b>{delivery_timestamp(order)}</b>\n"
        "━━━━━━━━━━━━━━"
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

    if getattr(product, "delivery_mode", "instant") == "manual":
        items = await allocate_stock_items(session, order)
        if len(items) != max(1, order.quantity or 1):
            raise RuntimeError("Not enough stock is available for this manual-delivery order.")
        await complete_stock_items(session, order.id)
        order.status = "paid_manual"
        await session.commit()
        await bot.send_message(
            order.user_id,
            (
                "✅ <b>Payment Confirmed</b>\n"
                "━━━━━━━━━━━━━━\n"
                f"🧾 Order ID: <b>#{order.id}</b>\n"
                f"📦 Product: <b>{escape(product.name)}</b>\n"
                f"🔢 Quantity: <b>{order.quantity or 1}</b>\n"
                f"🕒 Date & Time: <b>{delivery_timestamp(order)}</b>\n"
                "━━━━━━━━━━━━━━\n"
                "👤 This product uses manual delivery. Our team will send it shortly."
            ),
            parse_mode="HTML",
        )
        for admin_id in settings.admin_ids:
            try:
                await bot.send_message(admin_id, f"📦 Manual delivery required\nOrder #{order.id}\nProduct: {product.name}\nQty: {order.quantity}\nCustomer: {order.user_id}\nUse /deliverorder {order.id}")
            except Exception:
                pass
        return

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
                        caption=(
                            f"✅ Order Delivered\n"
                            f"Order ID: #{order.id}\n"
                            f"Product: {product.name}\n"
                            f"Item: {index} of {len(items)}\n"
                            f"Date & Time: {delivery_timestamp(order)}"
                        ),
                    )
                else:
                    text_items.append(
                    f"🎁 <b>Item {index} of {len(items)}</b>\n"
                    f"┌────────────────\n"
                    f"<code>{escape(item.content)}</code>\n"
                    f"└────────────────"
                )

            if text_items:
                await bot.send_message(
                    order.user_id,
                    (
                        delivery_header(order)
                        + "\n\n🔐 <b>Your Delivery Items</b>\n\n"
                        + "\n\n".join(text_items)
                        + note_block(order)
                        + "\n\n━━━━━━━━━━━━━━\n"
                        + "💛 Thank you for choosing Prime Hub.\n"
                        + "🛟 Need help? Open /help and select this order."
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
        raise RuntimeError("This product has no unique stock items. Add stock before delivery.")
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
        raise RuntimeError("This product has no unique stock items. Add stock before delivery.")
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
