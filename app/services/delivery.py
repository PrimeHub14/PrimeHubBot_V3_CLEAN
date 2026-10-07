from __future__ import annotations

from html import escape
from datetime import timezone
import csv
import io

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.db.models import Order, Product, StockItem
from app.config import settings
from app.services.loot_paglu import LootPagluClient, LootPagluError, is_paglu_product, get_paglu_service_id_for_product
from app.services.admin_notifications import notify_admins_new_sale
from app.db.repo import (
    allocate_stock_items,
    available_stock_count,
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
        service_id = get_paglu_service_id_for_product(order.product_id, order.product)
        if not service_id:
            raise RuntimeError(f"Product #{order.product_id} is not linked to any Paglu service ID")
        live = await client.stock(service_id=service_id)
        if live < quantity:
            raise RuntimeError(f"Not enough supplier stock is available. Only {live} item(s) remain.")

        order.supplier_source = "loot_paglu"
        order.supplier_status = "purchasing"
        await session.commit()

        try:
            result = await client.order(quantity, service_id=service_id)
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
            + f"Your {len(text_items)} delivery item(s) for <b>{escape(order.product.name if order.product else 'your order')}</b> are attached below as <b>TXT</b> and <b>CSV</b> files."
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
    try:
        await notify_admins_new_sale(bot, session, order)
    except Exception:
        pass


async def _deliver_ventebot_order(bot: Bot, session: AsyncSession, order: Order, target_v_id: int | None = None) -> None:
    from app.services.ventebot import ventebot_client, get_ventebot_target_id, VenteBotError

    v_id = target_v_id or get_ventebot_target_id(order.product)
    if not v_id:
        raise RuntimeError(f"Product #{order.product_id} is not linked to a VenteBot target ID")

    quantity = max(1, order.quantity or 1)
    v_order = await ventebot_client.create_order(
        ventebot_product_id=v_id,
        quantity=quantity,
        customer_reference=f"telegram_user_{order.user_id}",
    )

    v_order_id = (
        v_order.get("id")
        or v_order.get("order_id")
        or (v_order.get("order", {}).get("id") if isinstance(v_order.get("order"), dict) else None)
        or (v_order.get("data", {}).get("id") if isinstance(v_order.get("data"), dict) else None)
    )
    v_status = v_order.get("status") or (v_order.get("order", {}).get("status") if isinstance(v_order.get("order"), dict) else "PROCESSING")

    items = v_order.get("items") or []
    if not items and isinstance(v_order.get("order"), dict):
        items = v_order.get("order", {}).get("items") or []

    text_items = []
    if isinstance(items, list):
        for index, itm in enumerate(items, start=1):
            if isinstance(itm, dict):
                account_data = itm.get("account_data") or itm.get("credential") or itm.get("credentials") or itm.get("text")
                if account_data:
                    text_items.append((index, str(account_data)))

    # 1. Instant Stock Delivery (credentials immediately provided by VenteBot)
    if text_items:
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

        order.delivery_record = "\n\n".join(c for _, c in text_items)
        order.supplier_source = "ventebot"
        order.supplier_order_id = str(v_order_id or "")
        order.supplier_status = str(v_status or "COMPLETED")
        await mark_delivered(session, order)
        try:
            await notify_admins_new_sale(bot, session, order)
        except Exception:
            pass
        return

    # 2. Activation / Provisioning Queue (Activation services like Coursera Plus, Canva, etc.)
    # DO NOT send dummy "Status: ok" or mark order as delivered!
    order.supplier_source = "ventebot"
    order.supplier_order_id = str(v_order_id or "processing")
    order.supplier_status = str(v_status or "AWAITING_ACTIVATION")
    order.status = "processing"
    await session.commit()

    # Inform customer politely with professional activation receipt
    await bot.send_message(
        order.user_id,
        f"⏳ <b>Order #{order.id} — Activation In Progress</b>\n"
        "━━━━━━━━━━━━━━\n"
        f"📦 Product: <b>{escape(order.product.name)}</b>\n"
        f"🔢 Quantity: <b>{quantity}</b>\n"
        f"🕒 Placed: <b>{delivery_timestamp(order)}</b>\n"
        f"⚙️ Status: <b>Provisioning with Supplier</b>\n"
        "━━━━━━━━━━━━━━\n\n"
        "<i>Your subscription access / license is being activated in our supplier queue. Once activation is complete, your credentials will appear right here automatically.</i>\n\n"
        f"{note_block(order)}\n\n"
        "━━━━━━━━━━━━━━\n"
        "💛 Thank you for choosing Prime Hub.\n"
        "🛟 Need instant assistance? Open /help or contact our team.",
        parse_mode="HTML",
    )

    # High-priority alert to Admin with 1-tap re-check and manual delivery buttons
    admin_text = (
        f"⚠️ <b>VenteBot Activation Queue — Order #{order.id}</b>\n\n"
        f"👤 Customer: <code>{order.user_id}</code>\n"
        f"📦 Product: <b>{escape(order.product.name)}</b>\n"
        f"🌐 Vente Order ID: <code>{v_order_id or 'Pending'}</code>\n"
        f"📊 Supplier Status: <code>{v_status}</code>\n\n"
        "<i>VenteBot is processing this order. Tap below to re-check status or send manual credentials:</i>"
    )
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔄 Re-Check VenteBot Status", callback_data=f"venterecheck:{order.id}"),
            InlineKeyboardButton(text="✍️ Deliver Manual", callback_data=f"manualdeliverprompt:{order.id}"),
        ],
        [
            InlineKeyboardButton(text="🔎 Inspect Order Card", callback_data=f"admin_order_inspect:{order.id}"),
        ]
    ])
    for aid in settings.admin_ids:
        try:
            await bot.send_message(aid, admin_text, reply_markup=admin_kb, parse_mode="HTML")
        except Exception:
            pass


async def recheck_and_deliver_ventebot(bot: Bot, session: AsyncSession, order: Order) -> tuple[bool, str]:
    """Poll VenteBot for updated order status and deliver items if available."""
    from app.services.ventebot import ventebot_client

    if not order.supplier_order_id or not order.supplier_order_id.isdigit():
        return False, "No valid VenteBot numeric order ID found on this order."

    try:
        v_order = await ventebot_client.get_order(int(order.supplier_order_id))
    except Exception as exc:
        return False, f"VenteBot API Error: {exc}"

    v_status = v_order.get("status") or (v_order.get("order", {}).get("status") if isinstance(v_order.get("order"), dict) else "UNKNOWN")
    items = v_order.get("items") or []
    if not items and isinstance(v_order.get("order"), dict):
        items = v_order.get("order", {}).get("items") or []

    text_items = []
    if isinstance(items, list):
        for index, itm in enumerate(items, start=1):
            if isinstance(itm, dict):
                account_data = itm.get("account_data") or itm.get("credential") or itm.get("credentials") or itm.get("text")
                if account_data:
                    text_items.append((index, str(account_data)))

    order.supplier_status = str(v_status)

    if text_items:
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
        order.delivery_record = "\n\n".join(c for _, c in text_items)
        await mark_delivered(session, order)
        try:
            await notify_admins_new_sale(bot, session, order)
        except Exception:
            pass
        return True, f"✅ Order #{order.id} delivered successfully with {len(text_items)} credentials from VenteBot!"

    await session.commit()
    return False, f"Order status is: {v_status}. No credentials ready yet from supplier."



async def _send_stock_items(bot: Bot, session: AsyncSession, order: Order, product: Product, items: list[StockItem]) -> None:
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
                + "<b>TXT</b> and <b>CSV</b> files so you can download and save them easily."
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
    order.delivery_record = "\n\n".join(item.content for item in items if not item.is_file_id)


async def deliver_order(bot: Bot, session: AsyncSession, order: Order) -> None:
    if order.delivered:
        return

    product = order.product

    from app.services.ventebot import get_ventebot_target_id
    v_target_id = get_ventebot_target_id(product)
    if v_target_id:
        await _deliver_ventebot_order(bot, session, order, v_target_id)
        return

    if is_paglu_product(product.id, product):
        quantity = max(1, int(order.quantity or 1))
        # 1. SMART FALLBACK: If we have our own local stock, sell our own stock first! (100% pure profit)
        local_available = await repo.available_stock_count(session, product.id)
        if local_available >= quantity:
            items = await allocate_stock_items(session, order)
            if len(items) == quantity:
                try:
                    await _send_stock_items(bot, session, order, product, items)
                    order.supplier_source = "local_stock"
                    await mark_delivered(session, order)
                    try:
                        await notify_admins_new_sale(bot, session, order)
                    except Exception:
                        pass
                    return
                except Exception:
                    await release_stock_items(session, order.id)
                    raise

        # 2. If own stock is 0 or exhausted, automatically purchase from Paglu shop bot!
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
            await _send_stock_items(bot, session, order, product, items)
            order.supplier_source = "local_stock"
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
    try:
        await notify_admins_new_sale(bot, session, order)
    except Exception:
        pass

