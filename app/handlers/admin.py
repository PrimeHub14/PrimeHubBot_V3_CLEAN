from __future__ import annotations

from datetime import datetime, timezone
from html import escape
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.db.session import SessionLocal
from app.services.delivery import deliver_order
from app.services.loot_paglu import LootPagluClient, LootPagluError, live_stock, is_paglu_product
from app.services.announcements import notify_restock
from app.utils.security import is_admin

router = Router()


class AddProduct(StatesGroup):
    category = State()
    name = State()
    price = State()
    description = State()
    image = State()
    delivery = State()
    is_file_id = State()


class EditProduct(StatesGroup):
    value = State()


class ManualDelivery(StatesGroup):
    content = State()


EDITABLE_FIELDS = {
    "name": "Name",
    "price": "Price",
    "category": "Category",
    "description": "Description",
    "image": "Image",
    "delivery": "Delivery content",
    "delivery_note": "Delivery note",
}


def admin_only(message: Message) -> bool:
    return bool(message.from_user and is_admin(message.from_user.id))


async def existing_categories() -> list[str]:
    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=False)
    return sorted({p.category.strip() for p in products if p.category and p.category.strip() and not p.category.strip().startswith("/")})


def category_choice_kb(categories: list[str], prefix: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📂 {category}", callback_data=f"{prefix}:{index}")] for index, category in enumerate(categories)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_product_kb(product_id: int, active: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Name", callback_data=f"editproduct:{product_id}:name"),
                InlineKeyboardButton(text="💵 Price", callback_data=f"editproduct:{product_id}:price"),
            ],
            [
                InlineKeyboardButton(text="📂 Category", callback_data=f"editproduct:{product_id}:category"),
                InlineKeyboardButton(text="📄 Description", callback_data=f"editproduct:{product_id}:description"),
            ],
            [
                InlineKeyboardButton(text="🖼 Image", callback_data=f"editproduct:{product_id}:image"),
                InlineKeyboardButton(text="📦 Delivery", callback_data=f"editproduct:{product_id}:delivery"),
            ],
            [
                InlineKeyboardButton(text="📘 Delivery Note", callback_data=f"editproduct:{product_id}:delivery_note"),
            ],
            [
                InlineKeyboardButton(
                    text="🔴 Disable" if active else "🟢 Enable",
                    callback_data=f"toggleproduct:{product_id}",
                )
            ],
            [InlineKeyboardButton(text="✖ Close", callback_data="editproduct:close")],
        ]
    )


@router.message(Command("admin"))
async def admin(message: Message):
    if not admin_only(message):
        return
    await message.answer(
        "👤 <b>Prime Hub Admin Panel</b>\n\n"
        "📦 <b>Order & Delivery Management:</b>\n"
        "/adminorders - Recent orders dashboard\n"
        "/order ORDER_ID - Inspect order details & customer info\n"
        "/deliver ORDER_ID - Instant delivery of any order\n"
        "/delivermanual ORDER_ID [text] - Send custom credentials\n"
        "/stats - Store sales & user statistics\n"
        "/reports - Sales reports by date range\n"
        "/solddata - Exact sold-item ledger & CSV export\n\n"
        "🛍️ <b>Catalog & Stock:</b>\n"
        "/addproduct - Add product\n"
        "/listproducts - List products\n"
        "/editproduct PRODUCT_ID - Edit product\n"
        "/moveproduct PRODUCT_ID - Move product to category\n"
        "/deletecategory - Remove an empty category\n"
        "/delproduct PRODUCT_ID - Disable product\n"
        "/addstock PRODUCT_ID - Add stock (paste text or upload .txt file)\n"
        "/importstock PRODUCT_ID - Import stock from file\n"
        "/stock PRODUCT_ID - Check available stock\n"
        "/removestock PRODUCT_ID QTY - Reduce stock\n"
        "/disablestock PRODUCT_ID - Use reusable delivery\n"
        "/editnote PRODUCT_ID - Set customer instructions\n"
        "/viewnote PRODUCT_ID - View customer instructions\n\n"
        "📢 <b>Broadcasts & Support:</b>\n"
        "/postchannel MESSAGE - Post offer/update to Prime Hub channel\n"
        "/announce MESSAGE - Post to all update chats\n"
        "/broadcast - Send broadcast to users\n"
        "/ticketsadmin - Open support tickets\n"
        "/replyticket ID MESSAGE - Reply to a ticket\n\n"
        "🌐 <b>VenteBot Integration:</b>\n"
        "/ventestatus - Overview of all products & live link status\n"
        "/ventelist [search] - Browse & search VenteBot products\n"
        "/ventefile - Download full catalogue as .txt file\n"
        "/venteinfo ID - View item details & supplier stock\n"
        "/ventelink PRIMEHUB_ID VENTE_ID - Connect product\n"
        "/venteunlink PRIMEHUB_ID - Unlink product\n"
        "/venteme - Check VenteBot balance & status\n\n"
        "🤖 <b>Paglu Shop Bot Integration:</b>\n"
        "/paglustatus - Smart Fallback status & all linked products\n"
        "/paglulist - Browse all Paglu services, stock & wholesale rates\n"
        "/paglulink auto - Auto-link Adobe, Apple Music, Spotify, Gemini\n"
        "/paglulink PRIMEHUB_ID SERVICE_ID - Connect product manually\n"
        "/pagluunlink [PRIMEHUB_ID] - Disconnect Paglu bot\n"
        "/paglutest - Test Paglu API connectivity & wallet balance",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adminapprove:"))
async def approve_payment(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    order_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await call.answer("Order not found.", show_alert=True)
            return
        if order.delivered or order.status == "delivered":
            await call.answer("This order was already delivered.", show_alert=True)
            return

        await repo.set_order_status(session, order, "approved")
        try:
            await deliver_order(call.bot, session, order)
        except Exception as exc:
            message = str(exc)
            if "Not enough stock" in message:
                await repo.set_order_status(session, order, "paid_out_of_stock")
                try:
                    await call.bot.send_message(
                        order.user_id,
                        f"⚠️ Payment was confirmed for order #{order.id}, but the live stock sold out before confirmation. "
                        "Please contact support for a replacement or refund."
                    )
                except Exception:
                    pass
                await call.message.answer(
                    f"⚠️ Order #{order.id} is paid but live stock is unavailable. Arrange a replacement or refund."
                )
                await call.answer("Paid, but out of stock.", show_alert=True)
            else:
                await repo.set_order_status(session, order, "delivery_failed")
                await call.message.answer(f"⚠️ Payment approved, but delivery failed for order #{order.id}:\n{exc}")
                await call.answer("Delivery failed. Check the message.", show_alert=True)
            return

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if getattr(order.product, "delivery_mode", "instant") == "manual":
        await call.message.answer(f"✅ Order #{order_id} approved. Waiting for manual delivery; use /delivermanual {order_id}.")
        await call.answer("Approved; manual delivery pending.")
    else:
        await call.message.answer(f"✅ Order #{order_id} approved and delivered successfully to customer!")
        await call.answer("Approved and delivered.")


@router.callback_query(F.data.startswith("adminreject:"))
async def reject_payment(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    order_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await call.answer("Order not found.", show_alert=True)
            return
        if order.delivered:
            await call.answer("Delivered orders cannot be rejected.", show_alert=True)
            return
        await repo.set_order_status(session, order, "rejected")
        try:
            await call.bot.send_message(
                order.user_id,
                f"❌ Payment verification for Order #{order.id} could not be confirmed.\n\n"
                "Please check the amount/reference and contact support via /help or create a new order.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await call.message.answer(f"❌ Order #{order_id} rejected.")
    await call.answer("Rejected.")


@router.message(Command("addproduct"))
async def add_product(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    categories = await existing_categories()
    if not categories:
        await state.set_state(AddProduct.category)
        await message.answer("No existing categories found. Type the category name.")
        return
    await state.update_data(category_options=categories)
    await state.set_state(AddProduct.category)
    await message.answer(
        "📂 Choose the product category:",
        reply_markup=category_choice_kb(categories, "addcat"),
    )


@router.callback_query(AddProduct.category, F.data.startswith("addcat:"))
async def add_category_choice(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    data = await state.get_data()
    categories = data.get("category_options", [])
    try:
        category = categories[int(call.data.split(":")[1])]
    except (IndexError, ValueError):
        await call.answer("Category not found.", show_alert=True)
        return
    await state.update_data(category=category)
    await state.set_state(AddProduct.name)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"✅ Category: {category}\n\nProduct name? Example: Coursera Premium 12M")
    await call.answer()


@router.message(AddProduct.category)
async def add_category(message: Message, state: FSMContext):
    # Fallback only when the store has no categories yet.
    category = (message.text or "").strip()
    if not category or category.startswith("/"):
        await message.answer("Please type a valid category name without a slash.")
        return
    await state.update_data(category=category)
    await state.set_state(AddProduct.name)
    await message.answer("Product name? Example: Coursera Premium 12M")


@router.message(AddProduct.name)
async def add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddProduct.price)
    await message.answer("Price in USD? Example: 4.50")


@router.message(AddProduct.price)
async def add_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Please send a valid positive number, like 4.50")
        return
    await state.update_data(price=price)
    await state.set_state(AddProduct.description)
    await message.answer("Product description? Make it attractive.")


@router.message(AddProduct.description)
async def add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddProduct.image)
    await message.answer("Send product image/photo now, or type `skip`.", parse_mode="Markdown")


@router.message(AddProduct.image)
async def add_image(message: Message, state: FSMContext):
    image_file_id = None
    if message.photo:
        image_file_id = message.photo[-1].file_id
    elif message.text and message.text.strip().lower() == "skip":
        image_file_id = None
    else:
        await message.answer("Please send a photo, or type `skip`.")
        return
    await state.update_data(image_file_id=image_file_id)
    await state.set_state(AddProduct.delivery)
    await message.answer("Delivery content? Paste account/key/link/text to send after payment.")


@router.message(AddProduct.delivery)
async def add_delivery(message: Message, state: FSMContext):
    await state.update_data(delivery=message.text.strip())
    await state.set_state(AddProduct.is_file_id)
    await message.answer("Is this delivery a Telegram file_id? Reply yes or no.")


@router.message(AddProduct.is_file_id)
async def add_is_file(message: Message, state: FSMContext):
    answer = message.text.strip().lower()
    is_file_id = answer in {"yes", "y", "true", "1"}
    data = await state.get_data()
    async with SessionLocal() as session:
        product = await repo.create_product(
            session=session,
            category=data["category"],
            name=data["name"],
            price=data["price"],
            description=data["description"],
            delivery=data["delivery"],
            is_file_id=is_file_id,
            image_file_id=data.get("image_file_id"),
        )
    await state.clear()
    await message.answer(f"✅ Product added. ID: {product.id}\n\n⚠️ Stock is 0, so customers cannot order yet. Add stock with /addstock {product.id}")




@router.message(Command("paglustatus"))
async def paglu_status_command(message: Message):
    if not admin_only(message):
        return

    from app.services.loot_paglu import (
        is_paglu_enabled,
        get_paglu_service_id_for_product,
        LootPagluClient,
    )

    is_enabled = is_paglu_enabled()
    status_icon = "🟢 ACTIVE" if is_enabled else "⚪ UNLINKED / DISABLED"

    lines = [
        "🤖 <b>Paglu Shop Bot Integration Status</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"• <b>Connection Status:</b> {status_icon}",
        "• <b>Mode:</b> 🚀 <b>Smart Fallback</b> (Own Stock First ➔ Paglu Supplier Fallback)",
    ]

    client = LootPagluClient()
    wallet_info = "N/A"
    services_map: dict[str, dict] = {}
    if is_enabled:
        try:
            me = await client.me()
            wallet_info = f"₹{me.get('wallet_inr', 0)} INR | {me.get('wallet_crypto', 0)} Crypto"
            for s in await client.products():
                if isinstance(s, dict) and s.get("service_id"):
                    services_map[str(s.get("service_id")).strip().lower()] = s
        except Exception as exc:
            lines.append(f"⚠️ <i>Paglu API notice: {escape(str(exc))}</i>")

    lines.append(f"• <b>Paglu Wallet Balance:</b> <b>{wallet_info}</b>\n")

    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=False)

        linked_products = []
        unlinked_candidates = []
        for p in products:
            sid = get_paglu_service_id_for_product(p.id, p)
            if sid:
                local_stk = await repo.available_stock_count(session, p.id)
                supp_stk = 0
                s_obj = services_map.get(sid.lower())
                if s_obj:
                    supp_stk = max(0, int(s_obj.get("available_stock") or 0))
                else:
                    try:
                        supp_stk = await client.stock(sid)
                    except Exception:
                        supp_stk = 0
                tot = local_stk + supp_stk
                linked_products.append((p, sid, local_stk, supp_stk, tot, s_obj))
            else:
                p_name_lower = p.name.lower()
                if any(kw in p_name_lower for kw in ["adobe", "apple", "spotify", "gemini", "duolingo", "meesho"]):
                    unlinked_candidates.append(p)

    if linked_products:
        lines.append("📦 <b>Linked Products:</b>")
        for p, sid, local_stk, supp_stk, tot, s_obj in linked_products:
            p_name = escape(p.name)
            s_name = escape(str(s_obj.get("name") if s_obj else sid))
            lines.append(
                f"• <b>#{p.id} {p_name}</b> (${float(p.price):.2f})\n"
                f"   🔗 Service: <code>{sid}</code> ({s_name})\n"
                f"   📊 Own Stock: <b>{local_stk}</b> | Paglu: <b>{supp_stk}</b> (Total: <b>{tot}</b>)"
            )
    else:
        lines.append("⚠️ <i>No products are currently linked to Paglu services.</i>")

    if unlinked_candidates:
        lines.append("\n💡 <b>Unlinked Products Found in Your Store:</b>")
        for up in unlinked_candidates:
            lines.append(f"• <b>#{up.id} {escape(up.name)}</b> — Run <code>/paglulink auto</code> to link automatically!")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━\n💡 <b>Helpful Commands:</b>")
    lines.append("• <code>/paglulist</code> — View all available Paglu products, live stock & wholesale rates")
    lines.append("• <code>/paglulink auto</code> — Auto-detect & link Adobe, Apple Music, Spotify, Gemini")
    lines.append("• <code>/paglulink PRIMEHUB_ID SERVICE_ID</code> — Link specific product")
    lines.append("• <code>/pagluunlink [PRIMEHUB_ID]</code> — Unlink product")
    lines.append("• <code>/paglutest</code> — Test Paglu API connectivity")

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("paglulist"))
async def paglu_list_command(message: Message):
    if not admin_only(message):
        return

    from app.services.loot_paglu import LootPagluClient, LootPagluError

    client = LootPagluClient()
    try:
        services = await client.products(force_refresh=True)
        me = await client.me()
    except LootPagluError as exc:
        await message.answer(
            f"❌ <b>Paglu API Connection Error:</b>\n<code>{escape(str(exc))}</code>\n\n"
            f"💡 Make sure <code>LOOTPAGLU_BASE_URL</code> and <code>LOOTPAGLU_API_KEY</code> are configured in Railway.",
            parse_mode="HTML",
        )
        return
    except Exception as exc:
        await message.answer(f"❌ Failed to fetch Paglu services: {escape(str(exc))}")
        return

    if not services:
        await message.answer("⚠️ No services returned by Paglu API. Please check your supplier bot setup.")
        return

    lines = [
        "🌐 <b>Paglu Shop Bot — Available Catalogue</b>\n"
        f"💰 Wallet: <b>₹{me.get('wallet_inr', 0)} INR</b> | <b>{me.get('wallet_crypto', 0)} Crypto</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]

    async with SessionLocal() as session:
        primehub_prods = await repo.list_products(session, only_active=False)

    for idx, s in enumerate(services, start=1):
        s_id = s.get("service_id", "N/A")
        s_name = s.get("name", "Unknown")
        stock = s.get("available_stock", 0)
        slots = s.get("slots") or []
        price_str = ""
        if slots and isinstance(slots, list):
            first_slot = slots[0]
            upi_p = first_slot.get("upiPrice")
            cry_p = first_slot.get("cryptoPrice")
            price_str = f"₹{upi_p} / {cry_p} USDT"

        stk_badge = f"🟢 <b>{stock} in stock</b>" if int(stock) > 0 else "🔴 <i>Out of stock</i>"

        matched = next(
            (p for p in primehub_prods if getattr(p, "paglu_service_id", None) == s_id or (s_id == "Paglu_1" and "gemini" in p.name.lower())),
            None,
        )
        match_info = f"✅ Linked to <b>#{matched.id} {escape(matched.name)}</b>" if matched else "⚪ <i>Not linked</i>"

        lines.append(
            f"<b>{idx}. {escape(str(s_name))}</b>\n"
            f"   • Service ID: <code>{s_id}</code>\n"
            f"   • Live Stock: {stk_badge}\n"
            + (f"   • Wholesale: <b>{price_str}</b>\n" if price_str else "")
            + f"   • Status: {match_info}"
        )

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━━\n👉 <b>How to Link:</b>")
    lines.append("• <code>/paglulink auto</code> — Auto-link matching products (Adobe, Apple Music, Spotify, Gemini)")
    lines.append("• <code>/paglulink PRIMEHUB_ID SERVICE_ID</code> — Link manually (e.g. <code>/paglulink 7 Paglu_2</code>)")

    full_text = "\n".join(lines)
    if len(full_text) <= 4000:
        await message.answer(full_text, parse_mode="HTML")
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 3800:
                await message.answer(chunk, parse_mode="HTML")
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk:
            await message.answer(chunk, parse_mode="HTML")


@router.message(Command("pagluunlink"))
async def paglu_unlink_command(message: Message):
    if not admin_only(message):
        return

    from app.services.loot_paglu import set_product_paglu_service, set_paglu_enabled

    parts = (message.text or "").split()

    if len(parts) >= 2 and parts[1].isdigit():
        pid = int(parts[1])
        async with SessionLocal() as session:
            product = await repo.get_product(session, pid)
            if not product:
                await message.answer(f"❌ Product #{pid} not found.")
                return
            product.paglu_service_id = None
            set_product_paglu_service(pid, None)
            await session.commit()
            p_name = product.name
        await message.answer(
            f"🔌 <b>Product Unlinked!</b>\n\n"
            f"Product <b>#{pid} {escape(p_name)}</b> is now disconnected from Paglu shop bot.\n"
            f"It will now only use your own uploaded stock from <code>/addstock {pid}</code>.",
            parse_mode="HTML",
        )
        return

    if len(parts) >= 2 and parts[1].lower() == "all":
        set_paglu_enabled(False)
        async with SessionLocal() as session:
            products = await repo.list_products(session, only_active=False)
            for p in products:
                p.paglu_service_id = None
                set_product_paglu_service(p.id, None)
            await session.commit()
        await message.answer("🔌 <b>All products have been disconnected from Paglu Shop Bot.</b>", parse_mode="HTML")
        return

    await message.answer(
        "Usage:\n"
        "• <code>/pagluunlink PRODUCT_ID</code> — Unlink a specific product\n"
        "• <code>/pagluunlink all</code> — Disconnect all products from Paglu\n\n"
        "Tip: Check linked products with <code>/paglustatus</code>.",
        parse_mode="HTML",
    )


@router.message(Command("paglulink"))
async def paglu_link_command(message: Message):
    if not admin_only(message):
        return

    from app.services.loot_paglu import (
        set_paglu_enabled,
        set_product_paglu_service,
        LootPagluClient,
    )

    set_paglu_enabled(True)
    parts = (message.text or "").split()

    # Case 1: Auto link
    if len(parts) == 2 and parts[1].lower() in {"auto", "all"}:
        client = LootPagluClient()
        try:
            services = await client.products(force_refresh=True)
        except Exception as exc:
            await message.answer(f"❌ Failed to reach Paglu API: {escape(str(exc))}")
            return

        if not services:
            await message.answer("⚠️ No Paglu services available to link.")
            return

        linked_count = 0
        report = ["🚀 <b>Auto-Linking Prime Hub Products to Paglu Shop Bot:</b>\n"]

        # Map keyword patterns to services
        keyword_map = [
            (["adobe", "express"], "Adobe Express"),
            (["apple", "music"], "Apple Music"),
            (["spotify"], "Spotify"),
            (["gemini"], "Gemini"),
            (["duolingo"], "Duolingo"),
            (["meesho"], "Meesho"),
        ]

        async with SessionLocal() as session:
            products = await repo.list_products(session, only_active=False)

            for keywords, label in keyword_map:
                # Find matching product in Prime Hub
                matched_p = next(
                    (p for p in products if any(kw in p.name.lower() for kw in keywords)),
                    None,
                )
                if not matched_p:
                    continue

                # Find matching service in Paglu
                matched_s = next(
                    (s for s in services if any(kw in str(s.get("name", "")).lower() for kw in keywords)),
                    None,
                )
                if not matched_s:
                    continue

                sid = str(matched_s.get("service_id") or "").strip()
                if not sid:
                    continue

                matched_p.paglu_service_id = sid
                set_product_paglu_service(matched_p.id, sid)
                linked_count += 1
                stock = matched_s.get("available_stock", 0)
                report.append(
                    f"✅ <b>{escape(matched_p.name)}</b> (ID <code>#{matched_p.id}</code>)\n"
                    f"   ➔ Linked to: <code>{sid}</code> ({escape(str(matched_s.get('name', '')))} | {stock} in stock)\n"
                )

            await session.commit()

        if linked_count > 0:
            report.append(f"🎉 <b>Successfully linked {linked_count} product(s)!</b>")
            report.append("Smart Fallback is active: your local stock sells first, then Paglu bot delivers automatically.")
            report.append("\n💡 <i>View status anytime with <code>/paglustatus</code></i>")
            await message.answer("\n".join(report), parse_mode="HTML")
        else:
            await message.answer(
                "⚠️ No automatic keyword matches found.\n"
                "Please use manual linking:\n"
                "<code>/paglulink PRIMEHUB_ID SERVICE_ID</code>\n"
                "Tip: Run <code>/paglulist</code> to view all Service IDs.",
                parse_mode="HTML",
            )
        return

    # Case 2: Manual link: /paglulink PRODUCT_ID SERVICE_ID
    if len(parts) >= 3 and parts[1].isdigit():
        pid = int(parts[1])
        sid = parts[2].strip()

        async with SessionLocal() as session:
            product = await repo.get_product(session, pid)
            if not product:
                await message.answer(f"❌ Product #{pid} not found in your store.")
                return

            product.paglu_service_id = sid
            set_product_paglu_service(pid, sid)
            await session.commit()
            prod_name = product.name
            local_stock = await repo.available_stock_count(session, pid)

        # Check stock from Paglu
        client = LootPagluClient()
        supp_stock = 0
        s_name = sid
        try:
            s_obj = await client.service(sid)
            if s_obj:
                supp_stock = max(0, int(s_obj.get("available_stock") or 0))
                s_name = s_obj.get("name") or sid
        except Exception:
            pass

        await message.answer(
            f"✅ <b>Paglu Shop Bot Successfully Linked!</b>\n\n"
            f"📦 <b>Prime Hub Product:</b> <b>{escape(prod_name)}</b> (<code>#{pid}</code>)\n"
            f"🔗 <b>Paglu Service:</b> <code>{sid}</code> ({escape(str(s_name))})\n"
            f"📊 <b>Live Supplier Stock:</b> <b>{supp_stock} units</b>\n"
            f"🏠 <b>Your Local Stock:</b> <b>{local_stock} units</b>\n"
            f"🛒 <b>Total Available to Customers:</b> <b>{local_stock + supp_stock} units</b>\n\n"
            f"⚡ <b>Smart Fallback Mode:</b> <b>ACTIVE</b>\n"
            f"• If you add local stock (<code>/addstock {pid}</code>), customers get your stock first (100% pure profit!).\n"
            f"• If your stock runs out, the bot automatically purchases from Paglu shop bot with zero downtime!\n\n"
            f"💡 <i>Check status anytime with <code>/paglustatus</code></i>",
            parse_mode="HTML",
        )
        return

    # Case 3: Show usage
    await message.answer(
        "📋 <b>Paglu Shop Bot Linking:</b>\n\n"
        "⚡ <b>Fastest Way (Auto Link):</b>\n"
        "<code>/paglulink auto</code> — Automatically connects Adobe Express, Apple Music, Spotify, and Gemini!\n\n"
        "✍️ <b>Manual Link:</b>\n"
        "<code>/paglulink PRIMEHUB_ID SERVICE_ID</code>\n"
        "<i>Example:</i> <code>/paglulink 7 Paglu_2</code>\n\n"
        "💡 <i>Run <code>/paglulist</code> to view all available Paglu Service IDs and stock.</i>\n"
        "💡 <i>Run <code>/listproducts</code> to view your Prime Hub product IDs.</i>",
        parse_mode="HTML",
    )


@router.message(Command("paglutest"))
async def paglu_test(message: Message):
    if not admin_only(message):
        return
    from app.services.loot_paglu import LootPagluClient, LootPagluError
    client = LootPagluClient()
    try:
        me = await client.me()
        services = await client.products(force_refresh=True)
    except LootPagluError as exc:
        await message.answer(f"❌ Paglu API test failed:\n<code>{escape(str(exc))}</code>", parse_mode="HTML")
        return
    except Exception as exc:
        await message.answer(f"❌ Paglu API test connection error:\n<code>{escape(str(exc))}</code>", parse_mode="HTML")
        return

    lines = [
        "✅ <b>Paglu API Connected Successfully!</b>\n",
        f"• Base URL: <code>{client.base_url}</code>",
        f"• INR Wallet: <b>₹{me.get('wallet_inr', 0)}</b>",
        f"• Crypto Wallet: <b>{me.get('wallet_crypto', 0)}</b>",
        f"• Total Services in Catalogue: <b>{len(services)}</b>\n",
        "<b>Available Services Summary:</b>",
    ]
    for s in services[:8]:
        lines.append(f"• <code>{s.get('service_id')}</code> — <b>{escape(str(s.get('name')))}</b> ({s.get('available_stock', 0)} in stock)")

    lines.append("\n💡 Run <code>/paglulink auto</code> to link your products!")
    await message.answer("\n".join(lines), parse_mode="HTML")

@router.message(Command("listproducts"))
async def list_products(message: Message):
    if not admin_only(message):
        return
    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=False)
        vente_stock_map: dict[int, int] = {}
        try:
            from app.services.ventebot import ventebot_client
            if ventebot_client.is_configured():
                vente_stock_map = await ventebot_client.get_all_stock_map()
        except Exception:
            pass

        if not products:
            await message.answer("No products yet.")
            return

        lines = ["📦 <b>Prime Hub Products Catalog:</b>\n"]
        for p in products:
            status = "🟢" if p.active else "🔴"
            image = "🖼️" if p.image_file_id else "—"
            if p.ventebot_product_id:
                v_stock = vente_stock_map.get(int(p.ventebot_product_id), 0)
                stk_str = f"🟢 Stock: {v_stock}" if v_stock > 0 else "🔴 Stock: 0 (Supplier)"
                link_info = f"🔗 Vente #{p.ventebot_product_id} ({stk_str})"
            elif not p.stock_enabled or p.delivery_mode == "manual":
                link_info = "♾ Reusable / Manual"
            else:
                local_stk = await repo.available_stock_count(session, p.id)
                from app.services.loot_paglu import is_paglu_product, live_stock
                if is_paglu_product(p.id, p):
                    total_stk = await live_stock(p.id, local_stk, product=p)
                    paglu_stk = max(0, total_stk - local_stk)
                    link_info = f"🤖 Paglu (Own: {local_stk} + Paglu: {paglu_stk} = {total_stk})"
                else:
                    stk_str = f"🟢 Stock: {local_stk}" if local_stk > 0 else "🔴 OUT OF STOCK"
                    link_info = f"⚠️ Unlinked ({stk_str})"

            lines.append(
                f"<b>#{p.id}</b> {status} | {image} | <b>{escape(p.name)}</b>\n"
                f"   📂 {escape(p.category or 'General')} | 💵 ${float(p.price):.2f} | {link_info}"
            )

        lines.append("\n💡 <b>Helpful Commands:</b>")
        lines.append("• <code>/ventestatus</code> — Live VenteBot link status")
        lines.append("• <code>/paglustatus</code> — Paglu Smart Fallback status")
        lines.append("• <code>/pagluunlink</code> — Disconnect Paglu bot")
        lines.append("• <code>/ventelink PRIMEHUB_ID VENTE_ID</code> — Link product to supplier")
        lines.append("• <code>/editproduct PRIMEHUB_ID</code> — Edit price/details")

    full_text = "\n".join(lines)
    if len(full_text) <= 4000:
        await message.answer(full_text, parse_mode="HTML")
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 3800:
                await message.answer(chunk, parse_mode="HTML")
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk:
            await message.answer(chunk, parse_mode="HTML")


@router.message(Command("moveproduct"))
async def move_product_command(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /moveproduct PRODUCT_ID\nExample: /moveproduct 12")
        return
    product_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
    if not product:
        await message.answer("Product not found.")
        return
    categories = await existing_categories()
    categories = [c for c in categories if c != product.category]
    if not categories:
        await message.answer("No other category is available.")
        return
    await state.update_data(move_product_id=product_id, move_category_options=categories)
    await message.answer(
        f"📦 <b>{product.name}</b>\nCurrent category: {product.category}\n\nChoose the new category:",
        reply_markup=category_choice_kb(categories, "movecat"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("movecat:"))
async def move_product_category(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    data = await state.get_data()
    categories = data.get("move_category_options", [])
    product_id = data.get("move_product_id")
    try:
        category = categories[int(call.data.split(":")[1])]
    except (IndexError, ValueError):
        await call.answer("Category not found.", show_alert=True)
        return
    if not product_id:
        await call.answer("Move session expired. Run /moveproduct again.", show_alert=True)
        return
    async with SessionLocal() as session:
        product = await repo.update_product_field(session, int(product_id), "category", category)
    await state.clear()
    if not product:
        await call.answer("Product not found.", show_alert=True)
        return
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"✅ <b>{product.name}</b> moved to <b>{category}</b>.", parse_mode="HTML")
    await call.answer("Product moved.")


@router.message(Command("deletecategory"))
async def delete_category_command(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    categories = await existing_categories()
    if not categories:
        await message.answer("No categories found.")
        return
    await state.update_data(delete_category_options=categories)
    await message.answer(
        "🗑 Choose a category to remove.\n\nOnly an empty category can be removed safely.",
        reply_markup=category_choice_kb(categories, "delcat"),
    )


@router.callback_query(F.data.startswith("delcat:"))
async def delete_category_choice(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    data = await state.get_data()
    categories = data.get("delete_category_options", [])
    try:
        category = categories[int(call.data.split(":")[1])]
    except (IndexError, ValueError):
        await call.answer("Category not found.", show_alert=True)
        return
    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=False)
        assigned = [p for p in products if p.category == category]
    if assigned:
        await call.answer(
            f"{len(assigned)} product(s) still use this category. Move them first.",
            show_alert=True,
        )
        return
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"✅ Category <b>{category}</b> removed from the menu.\n"
        "Categories are generated from product category values, so an empty category disappears automatically.",
        parse_mode="HTML",
    )
    await call.answer("Category removed.")


@router.message(Command("editproduct"))
async def edit_product(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /editproduct PRODUCT_ID\nExample: /editproduct 1")
        return

    product_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)

    if not product:
        await message.answer("Product not found.")
        return

    await message.answer(
        f"✏️ <b>Edit Product #{product.id}</b>\n\n"
        f"Name: {product.name}\n"
        f"Price: ${float(product.price):.2f}\n"
        f"Category: {product.category}\n"
        f"Status: {'Active' if product.active else 'Disabled'}\n\n"
        "Choose what to edit:",
        reply_markup=edit_product_kb(product.id, product.active),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "editproduct:close")
async def close_edit_product(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Closed.")


@router.callback_query(F.data.startswith("editproduct:"))
async def choose_edit_field(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return

    parts = call.data.split(":")
    if len(parts) != 3:
        return
    product_id = int(parts[1])
    field = parts[2]
    if field not in EDITABLE_FIELDS:
        await call.answer("Unknown field.", show_alert=True)
        return

    await state.update_data(product_id=product_id, field=field)
    await state.set_state(EditProduct.value)

    if field == "image":
        prompt = "Send the new product photo, or type `remove` to delete the current image."
    elif field == "price":
        prompt = "Send the new price as a positive number, for example: 10.00"
    elif field == "delivery_note":
        prompt = (
            "Send the customer instructions for this product.\n\n"
            "You may use: {product_name}, {quantity}, {order_id}, {support_username}.\n"
            "Type `remove` to clear the note."
        )
    else:
        prompt = f"Send the new {EDITABLE_FIELDS[field].lower()}."

    await call.message.answer(prompt, parse_mode="Markdown")
    await call.answer()


@router.message(EditProduct.value)
async def save_edited_value(message: Message, state: FSMContext):
    if not admin_only(message):
        await state.clear()
        return

    data = await state.get_data()
    product_id = int(data["product_id"])
    field = data["field"]

    if field == "image":
        if message.photo:
            value = message.photo[-1].file_id
        elif message.text and message.text.strip().lower() == "remove":
            value = None
        else:
            await message.answer("Send a photo, or type `remove`.")
            return
    else:
        if not message.text:
            await message.answer("Please send text.")
            return
        value = message.text.strip()
        if field == "delivery_note" and value.lower() == "remove":
            value = ""
        if field == "price":
            try:
                value = float(value)
                if value <= 0:
                    raise ValueError
            except ValueError:
                await message.answer("Please send a valid positive number, for example: 10.00")
                return

    async with SessionLocal() as session:
        product = await repo.update_product_field(session, product_id, field, value)

    await state.clear()
    if not product:
        await message.answer("Product not found.")
        return

    display_value = f"${float(product.price):.2f}" if field == "price" else ("updated" if field == "image" else str(value))
    await message.answer(
        f"✅ {EDITABLE_FIELDS[field]} updated to: {display_value}\n\n"
        f"Use /editproduct {product_id} to edit another field."
    )


@router.callback_query(F.data.startswith("toggleproduct:"))
async def toggle_product(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    product_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        product = await repo.toggle_product_active(session, product_id)
    if not product:
        await call.answer("Product not found.", show_alert=True)
        return
    await call.message.edit_reply_markup(reply_markup=edit_product_kb(product.id, product.active))
    await call.answer("Product enabled." if product.active else "Product disabled.")


@router.message(Command("delproduct"))
async def del_product(message: Message):
    if not admin_only(message):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /delproduct PRODUCT_ID")
        return
    async with SessionLocal() as session:
        ok = await repo.deactivate_product(session, int(parts[1]))
    await message.answer("✅ Disabled." if ok else "Product not found.")


async def render_order_card(session: AsyncSession, order_id: int) -> tuple[str, InlineKeyboardMarkup | None]:
    order = await repo.get_order_with_product(session, order_id)
    if not order:
        return f"❌ Order #{order_id} not found.", None

    p_name = order.product.name if order.product else f"Product #{order.product_id}"
    user = order.user
    customer_name = " ".join(filter(None, [user.first_name, user.last_name])) if user else f"User {order.user_id}"
    username = f"@{user.username}" if user and user.username else "No username"

    inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))
    inr_val = float(order.amount) * inr_rate
    created_str = order.created_at.strftime("%d %b %Y, %H:%M UTC") if order.created_at else "Unknown"

    status_icon = "✅" if order.delivered else ("⌛" if order.status == "expired" else ("🔍" if order.payment_proof_value else "⏳"))

    lines = [
        f"🧾 <b>Order #{order.id} Details</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"📦 Product: <b>{escape(p_name)}</b>",
        f"🔢 Quantity: <b>{order.quantity or 1}</b>",
        f"💵 Total: <b>${float(order.amount):.2f}</b> (approx ₹{inr_val:,.2f})",
        f"💳 Method: <b>{escape(order.payment_method or 'Not set')}</b>",
        f"📊 Status: {status_icon} <b>{escape(order.status)}</b> (Delivered: {'Yes' if order.delivered else 'No'})",
        f"🕒 Created: <code>{created_str}</code>",
    ]

    if order.payment_proof_value:
        lines.append(f"🔢 UTR / Proof: <code>{escape(str(order.payment_proof_value))}</code>")
    if order.supplier_source:
        lines.append(f"🌐 Supplier: <b>{escape(order.supplier_source)}</b> (Ref #{order.supplier_order_id})")
    if order.delivery_record:
        snippet = str(order.delivery_record)[:120] + "..." if len(str(order.delivery_record)) > 120 else str(order.delivery_record)
        lines.append(f"🎁 Delivered Content:\n<code>{escape(snippet)}</code>")

    lines.extend([
        "",
        f"👤 <b>Customer Details:</b>",
        f"• Name: <b>{escape(customer_name)}</b>",
        f"• Username: <b>{escape(username)}</b>",
        f"• Telegram ID: <code>{order.user_id}</code>",
        "━━━━━━━━━━━━━━━━━━━━",
    ])

    buttons = []
    if not order.delivered:
        buttons.append([InlineKeyboardButton(text=f"🚀 Deliver Order #{order.id}", callback_data=f"adminapprove:{order.id}")])
        buttons.append([InlineKeyboardButton(text=f"✍️ Manual Deliver #{order.id}", callback_data=f"manualdeliverprompt:{order.id}")])
    else:
        buttons.append([InlineKeyboardButton(text="🔄 Force Re-deliver", callback_data=f"adminforcedeliver:{order.id}")])

    buttons.append([
        InlineKeyboardButton(text="💬 Message Customer", url=f"tg://user?id={order.user_id}"),
        InlineKeyboardButton(text="🔙 Back to Orders", callback_data="refreshadminorders"),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=buttons)


@router.message(Command("adminorders"))
async def orders(message: Message):
    if not admin_only(message):
        return
    async with SessionLocal() as session:
        orders_list = await repo.recent_orders(session, limit=15)
    if not orders_list:
        await message.answer("No orders yet.")
        return

    lines = ["🧾 <b>Recent Orders Dashboard</b>\n"]
    buttons = []
    current_row = []

    for o in orders_list:
        p_name = o.product.name[:22] if o.product else f"Product #{o.product_id}"
        username = f"@{o.user.username}" if o.user and o.user.username else f"ID:{o.user_id}"

        status_icon = "✅" if o.delivered else ("⌛" if o.status == "expired" else ("🔍" if o.payment_proof_value else "⏳"))
        utr_str = f" [UTR: {str(o.payment_proof_value)[:12]}]" if o.payment_proof_value else ""

        lines.append(
            f"{status_icon} <b>#{o.id}</b> · <b>{escape(p_name)}</b>\n"
            f"   👤 {escape(username)} · <b>${float(o.amount):.2f}</b> · {escape(o.status)}{utr_str}"
        )

        btn_text = f"{status_icon} #{o.id}"
        current_row.append(InlineKeyboardButton(text=btn_text, callback_data=f"adminorder:{o.id}"))
        if len(current_row) == 3:
            buttons.append(current_row)
            current_row = []

    if current_row:
        buttons.append(current_row)

    lines.append("\n<i>Tap any order button below to view details or deliver:</i>")
    await message.answer("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")


@router.callback_query(F.data == "refreshadminorders")
async def refresh_admin_orders(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    async with SessionLocal() as session:
        orders_list = await repo.recent_orders(session, limit=15)
    if not orders_list:
        await call.answer("No orders yet.", show_alert=True)
        return

    lines = ["🧾 <b>Recent Orders Dashboard</b>\n"]
    buttons = []
    current_row = []

    for o in orders_list:
        p_name = o.product.name[:22] if o.product else f"Product #{o.product_id}"
        username = f"@{o.user.username}" if o.user and o.user.username else f"ID:{o.user_id}"

        status_icon = "✅" if o.delivered else ("⌛" if o.status == "expired" else ("🔍" if o.payment_proof_value else "⏳"))
        utr_str = f" [UTR: {str(o.payment_proof_value)[:12]}]" if o.payment_proof_value else ""

        lines.append(
            f"{status_icon} <b>#{o.id}</b> · <b>{escape(p_name)}</b>\n"
            f"   👤 {escape(username)} · <b>${float(o.amount):.2f}</b> · {escape(o.status)}{utr_str}"
        )

        btn_text = f"{status_icon} #{o.id}"
        current_row.append(InlineKeyboardButton(text=btn_text, callback_data=f"adminorder:{o.id}"))
        if len(current_row) == 3:
            buttons.append(current_row)
            current_row = []

    if current_row:
        buttons.append(current_row)

    lines.append("\n<i>Tap any order button below to view details or deliver:</i>")
    try:
        await call.message.edit_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    except Exception:
        pass
    await call.answer()


@router.callback_query(F.data.startswith("adminorder:"))
async def admin_order_callback(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    order_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        text, markup = await render_order_card(session, order_id)
    await call.message.answer(text, reply_markup=markup, parse_mode="HTML")
    await call.answer()


@router.message(Command("adminorder"))
async def admin_inspect_order_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("ℹ️ <b>Usage:</b> <code>/order ORDER_ID</code>\nExample: <code>/order 193</code>", parse_mode="HTML")
        return
    order_id = int(parts[1])
    async with SessionLocal() as session:
        text, markup = await render_order_card(session, order_id)
    await message.answer(text, reply_markup=markup, parse_mode="HTML")


@router.message(Command("deliver"))
async def admin_instant_deliver_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("ℹ️ <b>Usage:</b> <code>/deliver ORDER_ID</code>\nExample: <code>/deliver 193</code>", parse_mode="HTML")
        return
    order_id = int(parts[1])

    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await message.answer(f"❌ Order #{order_id} not found.")
            return
        if order.delivered:
            await message.answer(f"⚠️ Order #{order_id} was already delivered.")
            return

        await message.answer(f"⏳ Delivering Order #{order_id} to customer <code>{order.user_id}</code>...")
        try:
            await deliver_order(message.bot, session, order)
            p_name = order.product.name if order.product else f"Product #{order.product_id}"
            await message.answer(
                f"✅ <b>Order #{order_id} Delivered Successfully!</b>\n\n"
                f"📦 Product: <b>{escape(p_name)}</b>\n"
                f"👤 Customer ID: <code>{order.user_id}</code>\n"
                f"Product credentials delivered straight to customer's chat.",
                parse_mode="HTML",
            )
        except Exception as exc:
            await message.answer(f"❌ Delivery failed for Order #{order_id}:\n{exc}")


@router.message(Command("delivermanual"))
async def admin_deliver_manual_command(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("ℹ️ <b>Usage:</b> <code>/delivermanual ORDER_ID [content]</code>\nExample: <code>/delivermanual 193 user:pass</code>", parse_mode="HTML")
        return
    order_id = int(parts[1])

    if len(parts) >= 3 and parts[2].strip():
        content = parts[2].strip()
        async with SessionLocal() as session:
            order = await repo.get_order_with_product(session, order_id)
            if not order:
                await message.answer(f"❌ Order #{order_id} not found.")
                return
            order.delivery_record = content
            await message.bot.send_message(
                order.user_id,
                f"✅ <b>Order #{order.id} Delivered</b>\n\n<code>{escape(content)}</code>\n\nThank you for choosing Prime Hub! 💛",
                parse_mode="HTML",
            )
            await repo.mark_delivered(session, order)
            try:
                from app.services.admin_notifications import notify_admins_new_sale
                await notify_admins_new_sale(message.bot, session, order)
            except Exception:
                pass
        await message.answer(f"✅ <b>Order #{order_id} manually delivered to customer!</b>", parse_mode="HTML")
    else:
        await state.set_state(ManualDelivery.content)
        await state.update_data(manual_order_id=order_id)
        await message.answer(f"Send the manual delivery content for Order #{order_id} now (text, photo, or document).")


@router.callback_query(F.data.startswith("manualdeliverprompt:"))
async def manual_deliver_prompt_callback(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    order_id = int(call.data.split(":")[1])
    await state.set_state(ManualDelivery.content)
    await state.update_data(manual_order_id=order_id)
    await call.message.answer(f"Send the manual delivery content for Order #{order_id} now (text, photo, or document).")
    await call.answer()


@router.callback_query(F.data.startswith("adminforcedeliver:"))
async def admin_forcedeliver_callback(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    order_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await call.answer("Order not found.", show_alert=True)
            return
        order.delivered = False
        try:
            await deliver_order(call.bot, session, order)
            await call.message.answer(f"✅ Order #{order_id} re-delivered to customer.")
            await call.answer("Delivered!")
        except Exception as exc:
            await call.message.answer(f"❌ Re-delivery failed: {exc}")
            await call.answer("Failed", show_alert=True)


@router.message(Command("postchannel"))
async def post_to_channel_command(message: Message):
    if not admin_only(message):
        return
    text = (message.text or "").partition(" ")[2].strip()
    if not text:
        await message.answer("ℹ️ <b>Usage:</b> <code>/postchannel Your announcement or offer message</code>", parse_mode="HTML")
        return
    targets = settings.update_chat_ids() if callable(settings.update_chat_ids) else settings.update_chat_ids
    if not targets:
        await message.answer(
            "⚠️ No channel is configured yet.\n\n"
            "To connect your channel:\n"
            "1. Add this bot as Admin to your Telegram channel.\n"
            "2. In Railway Variables, set <code>UPDATE_CHAT_IDS=@YourChannelUsername</code> (or channel ID).\n"
            "3. Redeploy.",
            parse_mode="HTML",
        )
        return
    from app.services.announcements import send_to_update_chats
    sent, failed = await send_to_update_chats(message.bot, text)
    await message.answer(f"📢 Channel broadcast sent to {sent} target(s). Failed: {failed}.")


@router.message(Command("stats"))
async def stats_cmd(message: Message):
    if not admin_only(message):
        return
    async with SessionLocal() as session:
        users, orders_count, revenue = await repo.stats(session)
    await message.answer(f"📊 Stats\nUsers: {users}\nOrders: {orders_count}\nRevenue: ${revenue:.2f}")


@router.message(Command("editnote"))
async def edit_note_command(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /editnote PRODUCT_ID\nExample: /editnote 1")
        return
    product_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
    if not product:
        await message.answer("Product not found.")
        return
    await state.update_data(product_id=product_id, field="delivery_note")
    await state.set_state(EditProduct.value)
    await message.answer(
        f"📘 Send the delivery instructions for <b>{product.name}</b>.\n\n"
        "Example:\n"
        "• Login at https://example.com\n"
        "• Do not change the recovery email\n"
        "• Replacement support: 24 hours\n\n"
        "Available placeholders: <code>{product_name}</code>, <code>{quantity}</code>, "
        "<code>{order_id}</code>, <code>{support_username}</code>.\n"
        "Type <code>remove</code> to clear the note.",
        parse_mode="HTML",
    )


@router.message(Command("viewnote"))
async def view_note_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /viewnote PRODUCT_ID\nExample: /viewnote 1")
        return
    product_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
    if not product:
        await message.answer("Product not found.")
        return
    note = product.delivery_note or "No delivery note is configured."
    await message.answer(
        f"📘 <b>Delivery note for {product.name}</b>\n\n<pre>{note}</pre>",
        parse_mode="HTML",
    )


class AddStock(StatesGroup):
    items = State()


@router.message(Command("addstock"))
async def add_stock_command(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer(
            "📋 <b>Usage:</b> <code>/addstock PRODUCT_ID</code>\n"
            "<i>Example:</i> <code>/addstock 6</code> (for Gemini)\n\n"
            "💡 <i>Tip: Run <code>/stock</code> or <code>/listproducts</code> to view all product IDs.</i>",
            parse_mode="HTML",
        )
        return
    product_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
        current_stock = await repo.available_stock_count(session, product_id) if product else 0
    if not product:
        await message.answer("❌ Product not found.")
        return
    await state.update_data(stock_product_id=product_id)
    await state.set_state(AddStock.items)
    await message.answer(
        f"📦 <b>Add Stock for {escape(product.name)}</b> (ID: <code>#{product.id}</code>)\n"
        f"📊 Current Available Stock: <b>{current_stock}</b>\n\n"
        "Choose how to upload your stock:\n\n"
        "📄 <b>Method 1 (Recommended for Bulk / 10+ items):</b>\n"
        "Upload a <b>.txt</b> file containing your links or keys (one per line). "
        "There is <b>NO LIMIT</b> — you can upload 20, 50, 100, or 1,000+ links at once!\n\n"
        "✍️ <b>Method 2 (Small amount):</b>\n"
        "Paste your links directly in this chat (one per line).",
        parse_mode="HTML",
    )


@router.message(AddStock.items)
async def receive_stock_items(message: Message, state: FSMContext):
    if not admin_only(message):
        await state.clear()
        return

    data = await state.get_data()
    product_id = int(data.get("stock_product_id", 0))
    if not product_id:
        await state.clear()
        await message.answer("❌ Session expired. Please run <code>/addstock PRODUCT_ID</code> again.", parse_mode="HTML")
        return

    items: list[str] = []
    source_label = "chat text"

    if message.document:
        doc = message.document
        file_name = doc.file_name or "stock.txt"
        source_label = f"file <code>{escape(file_name)}</code>"
        try:
            tg_file = await message.bot.get_file(doc.file_id)
            raw = await message.bot.download_file(tg_file.file_path)
            raw_bytes = raw.read() if hasattr(raw, "read") else raw
            try:
                content = raw_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                content = raw_bytes.decode("latin-1", errors="replace")

            if file_name.lower().endswith(".csv"):
                import csv
                import io
                for row in csv.reader(io.StringIO(content)):
                    if row and row[0].strip():
                        val = row[0].strip()
                        if val.lower() not in {"stock", "item", "content", "link", "links", "url", "redeem_link"}:
                            items.append(val)
            else:
                for line in content.splitlines():
                    val = line.strip()
                    if val and val.lower() not in {"stock", "item", "content", "link", "links", "url", "redeem_link"}:
                        items.append(val)
        except Exception as exc:
            await message.answer(f"❌ Failed to read document: {exc}")
            return
    elif message.text:
        items = [line.strip() for line in message.text.splitlines() if line.strip()]
    else:
        await message.answer(
            "⚠️ Please upload a <b>.txt / .csv</b> file or paste stock items as text (one item per line).",
            parse_mode="HTML",
        )
        return

    if not items:
        await message.answer("❌ No valid stock items found. Please check your text or file.")
        return

    async with SessionLocal() as session:
        added = await repo.add_stock_items(session, product_id, items)
        total = await repo.available_stock_count(session, product_id)
        product = await repo.get_product(session, product_id)

    await state.clear()
    await message.answer(
        f"✅ <b>Successfully added {added} stock item(s)</b> from {source_label}!\n"
        f"📦 <b>Available stock now:</b> {total}\n"
        f"🏷️ <b>Product:</b> {product.name if product else f'#{product_id}'}",
        parse_mode="HTML",
    )
    if product and added > 0:
        try:
            users_notified, chats_notified = await notify_restock(
                message.bot, product, added, total
            )
            if users_notified or chats_notified:
                await message.answer(
                    f"🔔 Restock notifications sent to {users_notified} subscriber(s) "
                    f"and {chats_notified} update chat(s)."
                )
        except Exception as exc:
            logging.warning(f"Restock notification failed: {exc}")


@router.message(Command("stock"))
async def stock_status(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    async with SessionLocal() as session:
        if len(parts) == 1:
            rows = await repo.all_product_stock(session)
            if not rows:
                await message.answer("No products found.")
                return
            lines = ["📦 <b>All Product Stock</b>"]
            for product, available, reserved in rows:
                available = await live_stock(product.id, available, product=product)
                mode = getattr(product, "delivery_mode", "instant")
                source = "Paglu API" if is_paglu_product(product.id, product) else mode
                status = "✅" if available > 0 else "❌"
                lines.append(f"{status} #{product.id} {product.name} | ${float(product.price):.2f} | Available: {available} | {source}")
            await message.answer("\n".join(lines), parse_mode="HTML")
            return
        if len(parts) != 2 or not parts[1].isdigit():
            await message.answer("Usage: /stock or /stock PRODUCT_ID")
            return
        product_id = int(parts[1])
        product = await repo.get_product(session, product_id)
        if not product:
            await message.answer("Product not found.")
            return
        local_available = await repo.available_stock_count(session, product_id)
        available = await live_stock(product_id, local_available, product=product)
    await message.answer(f"📦 <b>{product.name}</b>\nPrice: <b>${float(product.price):.2f}</b>\nAvailable stock: <b>{available}</b>\nDelivery: <b>{getattr(product, 'delivery_mode', 'instant')}</b>", parse_mode="HTML")


@router.message(Command("deliverymode"))
async def delivery_mode_command(message: Message):
    if not admin_only(message): return
    parts=(message.text or "").split()
    if len(parts)!=3 or not parts[1].isdigit() or parts[2].lower() not in {"instant","manual"}:
        await message.answer("Usage: /deliverymode PRODUCT_ID instant|manual")
        return
    async with SessionLocal() as session:
        product=await repo.set_delivery_mode(session,int(parts[1]),parts[2].lower())
    await message.answer(f"✅ Delivery mode set to {parts[2].lower()}" if product else "Product not found.")


@router.message(Command("setmanualstock"))
async def set_manual_stock(message: Message):
    if not admin_only(message): return
    parts=(message.text or "").split()
    if len(parts)!=3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Usage: /setmanualstock PRODUCT_ID QTY")
        return
    async with SessionLocal() as session:
        product=await repo.set_delivery_mode(session,int(parts[1]),"manual")
        if not product:
            await message.answer("Product not found."); return
        added=await repo.add_manual_stock_slots(session,int(parts[1]),int(parts[2]))
        total=await repo.available_stock_count(session,int(parts[1]))
    await message.answer(f"✅ Added {added} manual-delivery unit(s). Available: {total}")


@router.message(Command("deliverorder"))
async def deliver_order_command(message: Message, state: FSMContext):
    if not admin_only(message): return
    parts=(message.text or "").split()
    if len(parts)!=2 or not parts[1].isdigit():
        await message.answer("Usage: /deliverorder ORDER_ID")
        return
    async with SessionLocal() as session:
        order=await repo.get_order_with_product(session,int(parts[1]))
        if not order or order.delivered:
            await message.answer("Order not found or already delivered."); return
    await state.update_data(manual_order_id=int(parts[1]))
    await state.set_state(ManualDelivery.content)
    await message.answer("Send the manual delivery content now (text, photo, or document).")


@router.message(ManualDelivery.content)
async def send_manual_delivery(message: Message, state: FSMContext):
    if not admin_only(message): await state.clear(); return
    data=await state.get_data(); order_id=int(data["manual_order_id"])
    async with SessionLocal() as session:
        order=await repo.get_order_with_product(session,order_id)
        if not order or order.delivered:
            await message.answer("Order is already delivered."); await state.clear(); return
        if message.photo:
            order.delivery_record = f"PHOTO_FILE_ID:{message.photo[-1].file_id}"
            await message.bot.send_photo(order.user_id,message.photo[-1].file_id,caption=f"✅ Manual delivery for order #{order.id}")
        elif message.document:
            order.delivery_record = f"DOCUMENT_FILE_ID:{message.document.file_id}"
            await message.bot.send_document(order.user_id,message.document.file_id,caption=f"✅ Manual delivery for order #{order.id}")
        elif message.text:
            order.delivery_record = message.text
            await message.bot.send_message(order.user_id,f"✅ <b>Order #{order.id} delivered</b>\n\n{message.text}",parse_mode="HTML")
        else:
            await message.answer("Send text, photo, or document."); return
        await repo.mark_delivered(session,order)
        try:
            from app.services.admin_notifications import notify_admins_new_sale
            await notify_admins_new_sale(message.bot, session, order)
        except Exception:
            pass
    await state.clear(); await message.answer(f"✅ Order #{order_id} manually delivered.")


@router.message(Command("removestock"))
async def remove_stock_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Usage: /removestock PRODUCT_ID QUANTITY\nExample: /removestock 1 5")
        return
    product_id, quantity = int(parts[1]), int(parts[2])
    async with SessionLocal() as session:
        removed = await repo.remove_available_stock(session, product_id, quantity)
        remaining = await repo.available_stock_count(session, product_id)
    await message.answer(f"✅ Removed {removed} item(s).\n📦 Remaining stock: {remaining}")


@router.message(Command("disablestock"))
async def disable_stock_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /disablestock PRODUCT_ID")
        return
    async with SessionLocal() as session:
        ok = await repo.disable_stock_mode(session, int(parts[1]))
    await message.answer("✅ Stock mode disabled; reusable delivery content will be used." if ok else "Product not found.")


@router.message(Command("venteme"))
async def vente_me_command(message: Message):
    if not admin_only(message):
        return
    from app.services.ventebot import ventebot_client, VenteBotError
    if not ventebot_client.is_configured():
        await message.answer(
            "⚠️ <b>VenteBot API Key is not set.</b>\n\n"
            "Please add <code>VENTEBOT_API_KEY</code> in your Railway project Variables.",
            parse_mode="HTML",
        )
        return
    try:
        data = await ventebot_client.me()
        balance = data.get("wallet_balance", 0.0)
        username = data.get("username") or "N/A"
        key_name = data.get("key_name") or "Reseller Key"
        user_id = data.get("user_telegram_id") or "N/A"
        await message.answer(
            "🤖 <b>VenteBot Reseller Account Status</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User ID: <code>{user_id}</code> (@{username})\n"
            f"🔑 Key Name: <b>{key_name}</b>\n"
            f"💰 Wallet Balance: <b>${float(balance):.2f} USD</b>\n"
            f"🌐 API URL: <code>{ventebot_client.base_url}</code>\n\n"
            "⚡ <i>Connected and ready for automated fulfillment!</i>",
            parse_mode="HTML",
        )
    except Exception as exc:
        await message.answer(f"❌ Failed to connect to VenteBot: <code>{exc}</code>", parse_mode="HTML")


def make_vente_catalog_file(products: list[dict]) -> BufferedInputFile:
    lines = [
        "=" * 80,
        "VENTEBOT COMPLETE RESELLER CATALOGUE",
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Total Products Available: {len(products)}",
        "=" * 80,
        "",
        f"{'ID':<6} | {'Price USD':<10} | {'Stock':<10} | {'Warranty':<10} | {'Product Name'}",
        "-" * 80,
    ]
    for p in products:
        p_id = p.get("id")
        p_name = p.get("name", "Unknown")
        p_price = p.get("price_usd") or p.get("reseller_price_usd") or 0.0
        p_stock = p.get("stock")
        stock_str = "Unlimited" if p_stock is None else str(p_stock)
        warranty = f"{p.get('warranty_days', 0)}d"
        lines.append(f"#{p_id:<5} | ${float(p_price):<9.2f} | {stock_str:<10} | {warranty:<10} | {p_name}")

    lines.extend([
        "",
        "=" * 80,
        "HOW TO LINK A PRODUCT IN PRIMEHUB:",
        "1. Create your product in Prime Hub (via /admin -> /addproduct or admin panel)",
        "2. Note your Prime Hub product ID (e.g. #7)",
        "3. Find the matching VenteBot ID from this list (e.g. #180 for Warp)",
        "4. Run: /ventelink PRIMEHUB_ID VENTEBOT_ID (e.g. /ventelink 7 180)",
        "=" * 80,
    ])
    payload = "\n".join(lines).encode("utf-8")
    return BufferedInputFile(payload, filename="VenteBot_Complete_Catalog.txt")


def format_vente_page(products: list[dict], page: int = 1, page_size: int = 15) -> tuple[str, InlineKeyboardMarkup | None]:
    total = len(products)
    if total == 0:
        return "No products found.", None

    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * page_size
    page_products = products[start_idx : start_idx + page_size]

    lines = [
        f"📦 <b>VenteBot Products</b> (Page {page}/{total_pages} · {total} total)\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    ]
    for p in page_products:
        p_id = p.get("id")
        p_name = p.get("name")
        p_price = p.get("price_usd") or p.get("reseller_price_usd") or 0.0
        p_stock = p.get("stock")
        stock_str = "Unlimited" if p_stock is None else f"{p_stock} in stock"
        lines.append(f"• <code>#{p_id}</code> <b>{escape(str(p_name))}</b> — ${float(p_price):.2f} ({stock_str})")

    lines.append("\n💡 <b>Link:</b> <code>/ventelink PRIMEHUB_ID VENTE_ID</code>")
    lines.append("🔍 <b>Search:</b> <code>/ventelist &lt;keyword&gt;</code> (e.g. <code>/ventelist capcut</code>)")
    lines.append("📄 <b>Full export:</b> <code>/ventefile</code>")

    kb_rows = []
    nav_row = []
    if page > 1:
        nav_row.append(InlineKeyboardButton(text="⬅️ Prev", callback_data=f"ventepage:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="ventepage:noop"))
    if page < total_pages:
        nav_row.append(InlineKeyboardButton(text="Next ➡️", callback_data=f"ventepage:{page + 1}"))
    kb_rows.append(nav_row)

    kb_rows.append([
        InlineKeyboardButton(text="📥 Download Full Catalog (.txt)", callback_data="ventepage:export"),
    ])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb_rows)


def _extract_keywords(text: str) -> set[str]:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", (text or "").lower())
    words = cleaned.split()
    stop_words = {
        "a", "an", "the", "and", "or", "for", "with", "of", "to", "in", "on", "at",
        "private", "admin", "access", "premium", "standard", "official", "lifetime",
        "months", "month", "year", "years", "days", "day", "subscription", "account",
    }
    res = set()
    for w in words:
        if w not in stop_words and len(w) > 1:
            res.add(w)
    return res


def suggest_vente_match(prod_name: str, vente_products: list[dict]) -> dict | None:
    target_kw = _extract_keywords(prod_name)
    p_lower = prod_name.lower().strip()

    # 1. Exact or substring match first
    for vp in vente_products:
        v_name = str(vp.get("name", "")).lower().strip()
        if p_lower == v_name or p_lower in v_name or v_name in p_lower:
            return vp

    # 2. Keyword overlap match
    best_candidate = None
    best_score = 0
    for vp in vente_products:
        v_name = str(vp.get("name", "")).lower()
        v_kw = _extract_keywords(v_name)
        shared = target_kw.intersection(v_kw)
        score = len(shared)
        if score > best_score and score >= 1:
            best_score = score
            best_candidate = vp

    return best_candidate if best_score >= 1 else None


@router.message(Command("ventestatus"))
async def vente_status_command(message: Message):
    if not admin_only(message):
        return
    from app.services.ventebot import ventebot_client
    if not ventebot_client.is_configured():
        await message.answer("⚠️ Set <code>VENTEBOT_API_KEY</code> in Railway first.", parse_mode="HTML")
        return

    try:
        vente_products = await ventebot_client.get_products(force_refresh=True)
    except Exception as exc:
        await message.answer(f"❌ Could not connect to VenteBot: <code>{exc}</code>", parse_mode="HTML")
        return

    vente_dict = {int(p["id"]): p for p in vente_products if isinstance(p, dict) and "id" in p}

    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=False)

    if not products:
        await message.answer("No products found in Prime Hub database.")
        return

    lines = ["📊 <b>Prime Hub ⟷ VenteBot Integration Status</b>\n━━━━━━━━━━━━━━━━━━━━━━"]
    unlinked = []
    linked_active = 0
    linked_out_of_stock = 0

    for p in products:
        v_id = p.ventebot_product_id
        if v_id and int(v_id) in vente_dict:
            vp = vente_dict[int(v_id)]
            v_name = vp.get("name", "Unknown")
            v_stock = vp.get("stock")
            stock_val = 999 if v_stock is None else int(v_stock)
            stock_str = "Unlimited" if v_stock is None else f"{stock_val} in stock"
            v_cost = vp.get("reseller_price_usd") or vp.get("price_usd") or 0.0

            if stock_val > 0:
                linked_active += 1
                icon = "🟢"
            else:
                linked_out_of_stock += 1
                icon = "🔴"

            lines.append(
                f"{icon} <b>#{p.id} {escape(p.name)}</b> (${float(p.price):.2f})\n"
                f"   ↳ Linked to: <code>#{v_id}</code> {escape(str(v_name))}\n"
                f"   ↳ Supplier Stock: <b>{stock_str}</b> (Wholesale: ${float(v_cost):.2f})\n"
            )
        elif v_id:
            lines.append(
                f"⚠️ <b>#{p.id} {escape(p.name)}</b> (${float(p.price):.2f})\n"
                f"   ↳ Linked to: <code>#{v_id}</code> (NOT FOUND in supplier catalog)\n"
            )
            unlinked.append(p)
        else:
            unlinked.append(p)

    if unlinked:
        lines.append("━━━━━━━━━━━━━━━━━━━━━━\n⚠️ <b>UNLINKED PRODUCTS (Showing OUT OF STOCK):</b>\n")
        for up in unlinked:
            match = suggest_vente_match(up.name, vente_products)
            lines.append(f"❌ <b>#{up.id} {escape(up.name)}</b> (${float(up.price):.2f})")
            if match:
                m_id = match.get("id")
                m_name = match.get("name")
                m_stock = match.get("stock")
                m_cost = match.get("reseller_price_usd") or match.get("price_usd") or 0.0
                stk_lbl = "Unlimited" if m_stock is None else f"{m_stock} in stock"
                lines.append(f"   💡 Suggested Match: <code>#{m_id}</code> <b>{escape(str(m_name))}</b> ({stk_lbl} | ${float(m_cost):.2f})")
                lines.append(f"   👉 Run to link: <code>/ventelink {up.id} {m_id}</code>\n")
            else:
                clean_search = re.sub(r"[^a-zA-Z0-9]+", " ", up.name).strip().split()[0] if up.name else "search"
                lines.append(f"   🔍 Find ID: <code>/ventelist {escape(clean_search)}</code>\n   👉 Run: <code>/ventelink {up.id} VENTE_ID</code>\n")

    lines.append(
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📈 Total: <b>{len(products)}</b> | Linked In-Stock: <b>{linked_active}</b> | "
        f"Supplier OOS: <b>{linked_out_of_stock}</b> | Unlinked: <b>{len(unlinked)}</b>\n\n"
        f"🔄 <i>Cache was forcefully refreshed from supplier.</i>"
    )

    full_text = "\n".join(lines)
    if len(full_text) <= 4000:
        await message.answer(full_text, parse_mode="HTML")
    else:
        chunk = ""
        for line in lines:
            if len(chunk) + len(line) + 1 > 3800:
                await message.answer(chunk, parse_mode="HTML")
                chunk = line + "\n"
            else:
                chunk += line + "\n"
        if chunk:
            await message.answer(chunk, parse_mode="HTML")


@router.message(Command("ventelist"))
async def vente_list_command(message: Message):
    if not admin_only(message):
        return
    from app.services.ventebot import ventebot_client
    if not ventebot_client.is_configured():
        await message.answer("⚠️ Set <code>VENTEBOT_API_KEY</code> in Railway first.", parse_mode="HTML")
        return

    parts = (message.text or "").split(maxsplit=1)
    query = parts[1].strip() if len(parts) > 1 else ""

    try:
        products = await ventebot_client.get_products(force_refresh=True)
        if not products:
            await message.answer("No products returned from VenteBot.")
            return

        if query and query.lower() not in {"all", "file", "export"}:
            q_lower = query.lower()
            filtered = [
                p for p in products
                if q_lower in str(p.get("name", "")).lower()
                or q_lower in str(p.get("description", "")).lower()
                or q_lower == str(p.get("id"))
            ]
            if not filtered:
                await message.answer(
                    f"🔍 No VenteBot products found matching <b>'{escape(query)}'</b>.\n\n"
                    f"• Type <code>/ventelist</code> to browse all products page by page.\n"
                    f"• Type <code>/ventefile</code> to download the full catalogue text file.",
                    parse_mode="HTML",
                )
                return

            lines = [f"🔍 <b>VenteBot Results for '{escape(query)}'</b> ({len(filtered)} found):\n━━━━━━━━━━━━━━━━━━━━━━"]
            for p in filtered[:40]:
                p_id = p.get("id")
                p_name = p.get("name")
                p_price = p.get("price_usd") or p.get("reseller_price_usd") or 0.0
                p_stock = p.get("stock")
                stock_str = "Unlimited" if p_stock is None else f"{p_stock} in stock"
                lines.append(f"• <code>#{p_id}</code> <b>{escape(str(p_name))}</b> — ${float(p_price):.2f} ({stock_str})")

            lines.append("\n💡 <b>How to link:</b>")
            lines.append("<code>/ventelink PRIMEHUB_ID VENTE_ID</code> (e.g. <code>/ventelink 7 142</code>)")
            await message.answer("\n".join(lines), parse_mode="HTML")
            return

        if query.lower() in {"file", "export"}:
            doc = make_vente_catalog_file(products)
            await message.answer_document(
                doc,
                caption=f"📦 <b>VenteBot Complete Catalogue</b> ({len(products)} products)",
                parse_mode="HTML",
            )
            return

        text, kb = format_vente_page(products, page=1)
        await message.answer(text, reply_markup=kb, parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"❌ Error fetching VenteBot catalogue: <code>{exc}</code>", parse_mode="HTML")


@router.callback_query(F.data.startswith("ventepage:"))
async def vente_page_callback(call: CallbackQuery):
    if not (call.from_user and is_admin(call.from_user.id)):
        await call.answer("Admins only.", show_alert=True)
        return
    action = call.data.split(":", 1)[1]
    if action == "noop":
        await call.answer()
        return
    if action == "export":
        await call.answer("Generating catalogue file...")
        from app.services.ventebot import ventebot_client
        products = await ventebot_client.get_products(force_refresh=False)
        doc = make_vente_catalog_file(products)
        await call.message.answer_document(
            doc,
            caption=f"📄 <b>VenteBot Full Catalogue</b> ({len(products)} products)",
            parse_mode="HTML",
        )
        return

    try:
        page = int(action)
    except ValueError:
        await call.answer()
        return

    await call.answer()
    from app.services.ventebot import ventebot_client
    products = await ventebot_client.get_products(force_refresh=False)
    text, kb = format_vente_page(products, page=page)
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@router.message(Command("ventefile"))
async def vente_file_command(message: Message):
    if not admin_only(message):
        return
    from app.services.ventebot import ventebot_client
    if not ventebot_client.is_configured():
        await message.answer("⚠️ Set <code>VENTEBOT_API_KEY</code> in Railway first.", parse_mode="HTML")
        return
    try:
        await message.answer("⏳ Generating complete VenteBot product catalogue file...")
        products = await ventebot_client.get_products(force_refresh=True)
        if not products:
            await message.answer("No products returned from VenteBot.")
            return
        doc = make_vente_catalog_file(products)
        await message.answer_document(
            doc,
            caption=(
                f"📦 <b>VenteBot Complete Catalogue</b>\n"
                f"Total Products: <b>{len(products)}</b>\n\n"
                f"Open this text file to view all product IDs, names, prices, and live stock!\n"
                f"Use <code>/ventelink PRIMEHUB_ID VENTE_ID</code> to link any product."
            ),
            parse_mode="HTML",
        )
    except Exception as exc:
        await message.answer(f"❌ Error generating catalogue file: <code>{exc}</code>", parse_mode="HTML")


@router.message(Command("venteinfo"))
async def vente_info_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /venteinfo VENTEBOT_PRODUCT_ID\nExample: /venteinfo 16")
        return
    v_id = int(parts[1])
    from app.services.ventebot import ventebot_client
    if not ventebot_client.is_configured():
        await message.answer("⚠️ Set <code>VENTEBOT_API_KEY</code> in Railway first.", parse_mode="HTML")
        return
    try:
        products = await ventebot_client.get_products(force_refresh=False)
        target = next((p for p in products if int(p.get("id") or 0) == v_id), None)
        if not target:
            await message.answer(f"VenteBot product #{v_id} not found.")
            return

        name = target.get("name", "Unknown")
        desc = target.get("description", "No description")
        price = target.get("price_usd") or target.get("reseller_price_usd") or 0.0
        std_price = target.get("standard_price_usd")
        stock = target.get("stock")
        stock_str = "Unlimited" if stock is None else str(stock)
        warranty = target.get("warranty_days", 0)
        delivery_type = target.get("delivery_type", "instant")

        text = (
            f"ℹ️ <b>VenteBot Product Details:</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 VenteBot ID: <code>#{v_id}</code>\n"
            f"📦 Name: <b>{escape(str(name))}</b>\n"
            f"💵 Wholesale Cost: <b>${float(price):.2f} USD</b>\n"
            + (f"🏷️ Standard Cost: <b>${float(std_price):.2f} USD</b>\n" if std_price else "")
            + f"📦 Live Stock: <b>{stock_str}</b>\n"
            f"🛡️ Warranty: <b>{warranty} days</b>\n"
            f"⚡ Delivery Type: <b>{delivery_type}</b>\n"
            f"📝 Description: {escape(str(desc))}\n\n"
            f"💡 <b>To link to Prime Hub:</b>\n"
            f"<code>/ventelink &lt;PrimeHub_Product_ID&gt; {v_id}</code>"
        )
        await message.answer(text, parse_mode="HTML")
    except Exception as exc:
        await message.answer(f"❌ Error fetching product info: <code>{exc}</code>", parse_mode="HTML")


@router.message(Command("ventelink"))
async def vente_link_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Usage: /ventelink PRIMEHUB_PRODUCT_ID VENTEBOT_PRODUCT_ID\nExample: /ventelink 5 12")
        return
    primehub_id, ventebot_id = int(parts[1]), int(parts[2])
    async with SessionLocal() as session:
        product = await repo.get_product(session, primehub_id)
        if not product:
            await message.answer(f"Prime Hub product #{primehub_id} not found.")
            return
        product.ventebot_product_id = ventebot_id
        product.stock_enabled = False
        product.delivery_mode = "instant"
        await session.commit()
    await message.answer(
        f"✅ <b>Linked successfully!</b>\n\n"
        f"Prime Hub Product: <b>{product.name}</b> (<code>#{primehub_id}</code>)\n"
        f"VenteBot Wholesale ID: <code>#{ventebot_id}</code>\n"
        f"Selling Price: <b>${float(product.price):.2f} USD</b>\n"
        f"Category: <b>{product.category}</b>\n\n"
        "⚡ <i>Live stock and automated delivery are now connected to VenteBot!</i>",
        parse_mode="HTML",
    )


@router.message(Command("deletecategory"))
async def delete_category_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /deletecategory CATEGORY_NAME\nExample: /deletecategory Vente Services")
        return
    target_category = parts[1].strip()
    async with SessionLocal() as session:
        stmt = select(Product).where(Product.category.ilike(target_category))
        prods = list((await session.execute(stmt)).scalars().all())
        if not prods:
            await message.answer(f"No products found in category '{target_category}'.")
            return
        count = len(prods)
        for p in prods:
            await session.delete(p)
        await session.commit()
    await message.answer(f"🗑️ <b>Deleted category '{target_category}'</b> and removed {count} product(s).", parse_mode="HTML")


@router.message(Command("clearventeproducts"))
async def clear_vente_products_command(message: Message):
    if not admin_only(message):
        return
    async with SessionLocal() as session:
        stmt = select(Product).where(Product.category == "Vente Services")
        prods = list((await session.execute(stmt)).scalars().all())
        count = len(prods)
        for p in prods:
            await session.delete(p)
        await session.commit()
    await message.answer(f"🗑️ Cleaned up {count} auto-imported products from 'Vente Services'.\nYour custom categories are untouched.", parse_mode="HTML")


@router.message(Command("venteunlink"))
async def vente_unlink_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /venteunlink PRIMEHUB_PRODUCT_ID\nExample: /venteunlink 5")
        return
    primehub_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, primehub_id)
        if not product:
            await message.answer(f"Product #{primehub_id} not found.")
            return
        product.ventebot_product_id = None
        await session.commit()
    await message.answer(f"✅ Product #{primehub_id} ({product.name}) unlinked from VenteBot.")



