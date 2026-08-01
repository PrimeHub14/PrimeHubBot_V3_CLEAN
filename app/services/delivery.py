from html import escape
from datetime import timezone
import csv
import io

from aiogram import Bot
from aiogram.types import BufferedInputFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order
from app.config import settings
from app.services.loot_paglu import LootPagluClient, LootPagluError, is_paglu_product
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


def make_bulk_txt(order: Order, text_items: list[tuple[int, str]]) -> BufferedInputFile:
    lines = [
        "Prime Hub - Bulk Order Delivery",
        f"Order ID: #{order.id}",
        f"Product: {order.product.name}",
        f"Quantity: {order.quantity or 1}",
        f"Date & Time: {delivery_timestamp(order)}",
        "",
    ]
    for index, content in text_items:
        lines.extend([
            f"Item {index} of {order.quantity or len(text_items)}",
            "-" * 50,
            content,
            "",
        ])
    note = (order.product.delivery_note or "").strip()
    if note:
        lines.extend(["Important Instructions", "-" * 50, note, ""])
    payload = "\n".join(lines).encode("utf-8")
    return BufferedInputFile(payload, filename=f"PrimeHub_Order_{order.id}_Delivery.txt")


def make_bulk_csv(order: Order, text_items: list[tuple[int, str]]) -> BufferedInputFile:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "order_id",
        "product",
        "quantity",
        "item_number",
        "delivery_content",
        "order_date_utc",
    ])
    for index, content in text_items:
        writer.writerow([
            order.id,
            order.product.name,
            order.quantity or 1,
            index,
            content,
            delivery_timestamp(order),
        ])
    payload = output.getvalue().encode("utf-8-sig")
    return BufferedInputFile(payload, filename=f"PrimeHub_Order_{order.id}_Delivery.csv")


async def _deliver_paglu_order(bot: Bot, session: AsyncSession, order: Order) -> None:
    """Purchase the mapped Gemini product from Loot Paglu and deliver it safely.

    Supplier purchase data is committed before Telegram delivery so a Telegram
    send failure can be retried without buying the same supplier order twice.
    """
    import json

    quantity = max(1, int(order.quantity or 1))

    # If a previous attempt reached the supplier successfully, reuse the stored
    # delivery items instead of purchasing again.
    products = None
    if order.supplier_status == "purchased" and order.supplier_delivery_record:
        try:
            saved = json.loads(order.supplier_delivery_record)
            products = saved.get("products") if isinstance(saved, dict) else None
        except Exception:
            products = None

    if not products:
        # A network failure after the supplier accepted an order is ambiguous.
        # Never automatically retry such an attempt because that could double-buy.
        if order.supplier_status == "purchasing":
            raise RuntimeError(
                "Supplier purchase is in an uncertain state. Check Paglu order history before retrying."
            )

        client = LootPagluClient()
        live = await client.stock()
        if live < quantity:
            raise RuntimeError(f"Not enough supplier stock is available. Only {live} item(s) remain.")

        order.supplier_source = "loot_paglu"
        order.supplier_status = "purchasing"
        await session.commit()

        try:
            result = await client.order(quantity)
        except LootPagluError as exc:
            # Known HTTP/API failures mean the purchase was rejected and can be
            # retried later after the problem is corrected. Connection errors are
            # deliberately kept uncertain to avoid accidental duplicate purchases.
            if "connection error" not in str(exc).lower():
                order.supplier_status = "failed"
                await session.commit()
            raise RuntimeError(f"Paglu supplier order failed: {exc}") from exc

        products = result.get("products") or []
        order.supplier_order_id = str(result.get("order_id") or "") or None
        order.supplier_delivery_record = json.dumps(result, ensure_ascii=False)
        order.supplier_status = "purchased"
        await session.commit()

    if not isinstance(products, list) or len(products) < quantity:
        raise RuntimeError("Supplier delivery record does not contain all purchased items.")

    text_items = [(index, str(content)) for index, content in enumerate(products[:quantity], start=1)]
    if len(text_items) >= 5:
        await bot.send_message(
            order.user_id,
            delivery_header(order)
            + "\n\n📁 <b>Bulk delivery ready</b>\n"
            + f"Your {len(text_items)} Gemini delivery item(s) are attached below as <b>TXT</b> and <b>CSV</b> files."
            + note_block(order)
            + "\n\n━━━━━━━━━━━━━━\n💛 Thank you for choosing Prime Hub.",
            parse_mode="HTML",
        )
        await bot.send_document(order.user_id, make_bulk_txt(order, text_items), caption=f"📄 TXT delivery file — Order #{order.id}")
        await bot.send_document(order.user_id, make_bulk_csv(order, text_items), caption=f"📊 CSV delivery file — Order #{order.id}")
    else:
        rendered = [
            f"🎁 <b>Item {i} of {len(text_items)}</b>\n┌────────────────\n<code>{escape(content)}</code>\n└────────────────"
            for i, content in text_items
        ]
        await bot.send_message(
            order.user_id,
            delivery_header(order)
            + "\n\n🔐 <b>Your Delivery Items</b>\n\n"
            + "\n\n".join(rendered)
            + note_block(order)
            + "\n\n━━━━━━━━━━━━━━\n💛 Thank you for choosing Prime Hub.\n🛟 Need help? Open /help and select this order.",
            parse_mode="HTML",
        )

    order.delivery_record = "\n\n".join(str(x) for x in products[:quantity])
    await mark_delivered(session, order)


async def deliver_order(bot: Bot, session: AsyncSession, order: Order) -> None:
    if order.delivered:
        return

    product = order.product

    if is_paglu_product(product.id):
        await _deliver_paglu_order(bot, session, order)
        return

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
            text_items: list[tuple[int, str]] = []
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
                    text_items.append((index, item.content))

            if text_items and len(text_items) >= 5:
                await bot.send_message(
                    order.user_id,
                    (
                        delivery_header(order)
                        + "\n\n📁 <b>Bulk delivery ready</b>\n"
                        + f"Your {len(text_items)} text delivery item(s) are attached below as "
                          "<b>TXT</b> and <b>CSV</b> files so you can download and save them easily."
                        + note_block(order)
                        + "\n\n━━━━━━━━━━━━━━\n"
                        + "💛 Thank you for choosing Prime Hub."
                    ),
                    parse_mode="HTML",
                )
                await bot.send_document(
                    order.user_id,
                    make_bulk_txt(order, text_items),
                    caption=f"📄 TXT delivery file — Order #{order.id}",
                )
                await bot.send_document(
                    order.user_id,
                    make_bulk_csv(order, text_items),
                    caption=f"📊 CSV delivery file — Order #{order.id}",
                )
            elif text_items:
                rendered_items = [
                    (
                        f"🎁 <b>Item {index} of {len(items)}</b>\n"
                        f"┌────────────────\n"
                        f"<code>{escape(content)}</code>\n"
                        f"└────────────────"
                    )
                    for index, content in text_items
                ]
                await bot.send_message(
                    order.user_id,
                    (
                        delivery_header(order)
                        + "\n\n🔐 <b>Your Delivery Items</b>\n\n"
                        + "\n\n".join(rendered_items)
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
