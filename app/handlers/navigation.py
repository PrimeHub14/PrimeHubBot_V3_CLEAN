import logging
from html import escape
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal
from app.i18n import tr
from app.keyboards import order_history_kb, categories_kb, main_menu_kb, wallet_home_kb, product_kb, meta_gemini_landing_kb
from app.services.loot_paglu import live_stock
from app.utils.security import is_admin

router = Router()


def _welcome_text(first_name: str | None = None) -> str:
    name = first_name or "friend"
    return (
        f"👋 Welcome, <b>{name}</b>!\n\n"
        f"🛍️ <b>{settings.STORE_NAME.replace('PrimeHub', 'Prime Hub')}</b>\n"
        "Premium digital products with fast delivery.\n\n"
        "⚡ <b>Instant Auto Verification</b> for Crypto, Binance Pay & UPI\n"
        "📦 <b>24/7 Instant Delivery</b> immediately after payment\n"
        "🛡️ Dedicated order history and customer support\n\n"
        "Choose an option below 👇"
    )


async def _register_user(message: Message, source: str | None = None) -> None:
    if not message.from_user:
        return
    async with SessionLocal() as session:
        await repo.upsert_user(session, message.from_user, source=source)
        text = message.text or ''
        if text.startswith('/start ref_'):
            await repo.set_referrer_from_code(session, message.from_user.id, text.split('ref_', 1)[1].strip())
        elif source and ("meta" in source.lower() or "gemini" in source.lower()):
            await repo.record_meta_lead(session, message.from_user.id, source)


async def _show_home(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _register_user(message)

    first_name = message.from_user.first_name if message.from_user else None
    name = first_name or "friend"

    text = (
        f"👋 Welcome, <b>{escape(name)}</b>!\n\n"
        "🛍 <b>Prime Hub Store</b>\n"
        "Premium digital products with fast delivery.\n\n"
        "⚡ <b>Instant Auto Verification</b> for Crypto, Binance Pay & UPI\n"
        "📦 <b>24/7 Instant Delivery</b> immediately after payment\n"
        "🛡️ Dedicated order history and customer support\n\n"
        "Choose an option below 👇"
    )

    if settings.WELCOME_IMAGE_FILE_ID:
        await message.answer_photo(
            settings.WELCOME_IMAGE_FILE_ID,
            caption=text,
            reply_markup=main_menu_kb(),
            parse_mode="HTML",
        )
    else:
        await message.answer(
            text,
            reply_markup=main_menu_kb(),
            parse_mode="HTML",
        )

@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext) -> None:
    text = message.text or ""
    payload = text.split(maxsplit=1)[1].strip().lower() if len(text.split(maxsplit=1)) > 1 else ""

    is_meta_gemini = bool(
        payload
        and (
            payload.startswith("gemini")
            or payload.startswith("meta")
            or "gemini" in payload
        )
    )

    if is_meta_gemini:
        await state.clear()
        await _register_user(message, source=payload)

        async with SessionLocal() as session:
            products = await repo.search_products(session, "Gemini", limit=20)

            product = next(
                (
                    p for p in products
                    if "gemini" in p.name.lower()
                    and ("18 month" in p.name.lower() or "18-month" in p.name.lower() or "18m" in p.name.lower())
                ),
                None,
            )
            if not product and products:
                product = products[0]

            if product:
                local_stock = await repo.available_stock_count(session, product.id)
                available_stock = await live_stock(product.id, local_stock)

        if product:
            safe_name = escape(product.name or "Gemini AI Pro 18 Months")
            safe_cat = escape(product.category or "AI Tools")
            first_name = message.from_user.first_name if message.from_user else "friend"
            price_val = float(product.price)

            caption = (
                f"🎁 <b>GEMINI AI PRO + 5TB + ANTIGRAVITY — 18 Months</b>\n"
                f"<i>⚡ Single-Click Activation On Your Own Email</i>\n\n"
                f"Welcome, <b>{escape(first_name)}</b>! Your exclusive Meta deal is unlocked:\n"
                f"Original: <s>₹35,999</s> • Regular: <s>₹799</s>\n"
                f"🔥 <b>TODAY'S SPECIAL: JUST ₹199 ONLY!</b>\n\n"
                f"📦 <b>Your 18-Month Package Includes:</b>\n"
                f"• <b>5TB Storage</b> (Google Drive + Gmail + Photos)\n"
                f"• <b>Gemini Advanced AI</b> & Deep Reasoning\n"
                f"• <b>Nano Banana Pro & Veo 3</b>\n"
                f"• <b>Google Flow & Whisk</b> (1,000 credits/mo)\n"
                f"• <b>Antigravity Access & NotebookLM</b>\n"
                f"• <b>Gemini Code Assist & CLI</b>\n"
                f"• <b>Add Up to 5 Family Members</b>\n"
                f"• <b>🛡️ 1-Month Replacement Warranty</b>\n\n"
                f"⚡ <b>How It Works:</b>\n"
                f"Receive Redeem Link → Open in Chrome → Select your own Google account → Click Activate Plan!\n\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"💵 Price: <b>₹199 (${price_val:.2f})</b>\n"
                f"📦 Available Redeem Codes: <b>{available_stock} slots</b>"
            )

            if available_stock <= 0:
                caption += "\n\n⚠️ <i>Current redeem batch is temporarily sold out due to high Meta ad demand. Click below to pre-order or contact support!</i>"
            else:
                caption += "\n\n👇 <i>Tap below to pay instantly via UPI, Binance, USDT or Wallet:</i>"

            kb = meta_gemini_landing_kb(product.id, price_val, available_stock)
            sent = False
            photo_to_send = product.image_file_id
            if not photo_to_send:
                import os
                local_static_img = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "gemini_poster.jpg")
                if not os.path.exists(local_static_img):
                    local_static_img = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static", "gemini_model.jpg")
                if os.path.exists(local_static_img):
                    from aiogram.types import FSInputFile
                    photo_to_send = FSInputFile(local_static_img)

            if photo_to_send:
                try:
                    if len(caption) <= 1024:
                        await message.answer_photo(
                            photo_to_send,
                            caption=caption,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                    else:
                        await message.answer_photo(photo_to_send)
                        await message.answer(
                            caption,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                    sent = True
                except Exception as exc:
                    logging.warning(f"Failed to send navigation photo for #{product.id} ({exc}), falling back to text.")

            if not sent:
                try:
                    await message.answer(
                        caption,
                        reply_markup=kb,
                        parse_mode="HTML",
                    )
                except Exception as exc:
                    logging.warning(f"Failed to send HTML navigation message for #{product.id} ({exc}), falling back to plain text.")
                    plain_caption = (
                        f"🔥 {product.name}\n\n"
                        f"Promo Price: ${price_val:.2f}\n"
                        f"Available Slots: {available_stock}\n\n"
                        "Delivery: Instant after confirmation\n"
                        "Support: 24/7 Available"
                    )
                    await message.answer(plain_caption, reply_markup=kb)
            return

    # 2. Universal Product / Category Deep Link (e.g. ?start=p_12, ?start=chatgpt, ?start=spotify)
    if payload and not payload.startswith("ref_"):
        await state.clear()
        await _register_user(message, source=payload)

        matched_product = None
        target_category = None

        if payload.startswith("cat_"):
            target_category = payload[4:].strip()

        async with SessionLocal() as session:
            pid = None
            if payload.startswith("p_") and payload[2:].isdigit():
                pid = int(payload[2:])
            elif payload.startswith("prod_") and payload[5:].isdigit():
                pid = int(payload[5:])
            elif payload.isdigit():
                pid = int(payload)

            if pid:
                p = await repo.get_product(session, pid)
                if p and p.active:
                    matched_product = p
            elif not target_category:
                clean_term = payload.replace("_", " ").replace("-", " ").strip()
                candidates = await repo.search_products(session, clean_term, limit=10)
                if candidates:
                    matched_product = candidates[0]

            if matched_product:
                from app.handlers.user import product_available_stock, product_caption
                available_stock = await product_available_stock(session, matched_product)
                caption = product_caption(matched_product, available_stock)
                kb = product_kb(matched_product.id, available_stock, category=matched_product.category)

                sent = False
                if matched_product.image_file_id:
                    try:
                        await message.answer_photo(
                            photo=matched_product.image_file_id,
                            caption=caption,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                        sent = True
                    except Exception as exc:
                        logging.warning(f"Failed to send deep link photo for #{matched_product.id}: {exc}")

                if not sent:
                    await message.answer(
                        text=caption,
                        reply_markup=kb,
                        parse_mode="HTML",
                    )
                return

            if target_category:
                from app.handlers.user import product_stock_map, product_list_kb
                cat_products = await repo.list_products_by_category(session, target_category)
                if cat_products:
                    stock_counts = await product_stock_map(session, cat_products)
                    await message.answer(
                        f"📂 <b>{escape(target_category)}</b>",
                        reply_markup=product_list_kb(cat_products, stock_counts),
                        parse_mode="HTML",
                    )
                    return

    await _show_home(message, state)

@router.message(Command("menu"))
async def menu_command(message: Message, state: FSMContext) -> None:
    await _show_home(message, state)


@router.message(Command("shop"))
async def shop_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _register_user(message)
    async with SessionLocal() as session:
        categories = await repo.list_categories(session)
        stock_totals, all_stock = await repo.category_stock_totals(session)
    if not categories:
        await message.answer("No products are available yet.", reply_markup=main_menu_kb())
        return
    await message.answer(
        "📂 <b>Choose a category</b>",
        reply_markup=categories_kb(categories, stock_totals, all_stock),
        parse_mode="HTML",
    )


@router.message(Command("wallet"))
async def wallet_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _register_user(message)
    async with SessionLocal() as session:
        balance = await repo.wallet_balance(session, message.from_user.id)
    await message.answer(
        "💰 <b>Prime Hub Wallet</b>\n\n"
        f"Available balance: <b>${balance:.2f}</b>\n\n"
        "Wallet purchases are confirmed and delivered instantly.",
        reply_markup=wallet_home_kb(),
        parse_mode="HTML",
    )


@router.message(Command("order", "orders"))
async def orders_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    parts = (message.text or "").split()
    if len(parts) >= 2 and parts[1].isdigit() and message.from_user and is_admin(message.from_user.id):
        from app.handlers.admin import render_order_card
        order_id = int(parts[1])
        async with SessionLocal() as session:
            text, markup = await render_order_card(session, order_id)
        await message.answer(text, reply_markup=markup, parse_mode="HTML")
        return

    await _register_user(message)
    async with SessionLocal() as session:
        orders = await repo.user_orders(session, message.from_user.id, limit=20)

    if not orders:
        await message.answer(
            "📦 <b>Order History</b>\n\nYou do not have any completed purchases yet.",
            reply_markup=main_menu_kb(),
            parse_mode="HTML",
        )
        return

    await message.answer(
        "📦 <b>Order History</b>\n\nSelect a completed order to view full details:",
        reply_markup=order_history_kb(orders),
        parse_mode="HTML",
    )


@router.message(Command("profile"))
async def profile_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _register_user(message)
    async with SessionLocal() as session:
        balance = await repo.wallet_balance(session, message.from_user.id)
        orders = await repo.user_orders(session, message.from_user.id, limit=100)

    username = f"@{message.from_user.username}" if message.from_user.username else "Not set"
    completed = sum(1 for order in orders if order.status in {"paid", "finished", "delivered"} or order.delivered)
    await message.answer(
        "👤 <b>My Profile</b>\n\n"
        f"Name: <b>{message.from_user.full_name}</b>\n"
        f"Username: <b>{username}</b>\n"
        f"Telegram ID: <code>{message.from_user.id}</code>\n"
        f"Wallet balance: <b>${balance:.2f}</b>\n"
        f"Total orders: <b>{len(orders)}</b>\n"
        f"Completed orders: <b>{completed}</b>",
        parse_mode="HTML",
    )




@router.callback_query(F.data == "growth:referral")
async def growth_referral_callback(call: CallbackQuery):
    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        code = await repo.ensure_referral_code(session, call.from_user.id)
        invited, earned = await repo.referral_stats(session, call.from_user.id)
    me = await call.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{code}"
    await call.message.answer(
        f"🎁 <b>Referral Program</b>\n\n<code>{link}</code>\n\nInvited: <b>{invited}</b>\nEarned: <b>${earned:.2f}</b>",
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "growth:loyalty")
async def growth_loyalty_callback(call: CallbackQuery):
    async with SessionLocal() as session:
        user = await repo.upsert_user(session, call.from_user)
    await call.message.answer(
        f"🏆 <b>Loyalty</b>\n\nPoints: <b>{int(user.loyalty_points or 0)}</b>\nVIP: <b>{user.vip_tier or 'Bronze'}</b>",
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data == "growth:recommend")
async def growth_recommend_callback(call: CallbackQuery):
    async with SessionLocal() as session:
        products = await repo.recommendations(session, call.from_user.id)
    rows = [[InlineKeyboardButton(text=f"{p.name} · ${float(p.price):.2f}", callback_data=f"product:{p.id}")] for p in products]
    if not rows:
        await call.answer("No recommendations yet.", show_alert=True); return
    await call.message.answer("🧠 <b>Recommended for You</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    await call.answer()
