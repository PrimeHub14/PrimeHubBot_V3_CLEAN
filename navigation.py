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
from app.keyboards import order_history_kb, categories_kb, main_menu_kb, wallet_home_kb, product_kb
from app.services.loot_paglu import live_stock

router = Router()


def _welcome_text(first_name: str | None = None) -> str:
    name = first_name or "friend"
    return (
        f"👋 Welcome, <b>{name}</b>!\n\n"
        f"🛍️ <b>{settings.STORE_NAME.replace('PrimeHub', 'Prime Hub')}</b>\n"
        "Premium digital products with fast delivery.\n\n"
        "✅ Automatic crypto confirmation\n"
        "✅ Manual Binance & UPI approval\n"
        "✅ Instant wallet purchases\n"
        "✅ Order history and support\n\n"
        "Choose an option below 👇"
    )


async def _register_user(message: Message) -> None:
    if not message.from_user:
        return
    async with SessionLocal() as session:
        await repo.upsert_user(session, message.from_user)
        text = message.text or ''
        if text.startswith('/start ref_'):
            await repo.set_referrer_from_code(session, message.from_user.id, text.split('ref_', 1)[1].strip())


async def _show_home(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _register_user(message)

    first_name = message.from_user.first_name if message.from_user else None
    name = first_name or "friend"

    text = (
        f"👋 Welcome, <b>{escape(name)}</b>!\n\n"
        "🛍 <b>Prime Hub Store</b>\n"
        "Premium digital products with fast delivery.\n\n"
        "✅ Automatic crypto confirmation\n"
        "✅ Manual Wallet, Binance & UPI approval\n"
        "✅ Instant delivery after approval\n"
        "✅ Order history and support\n\n"
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

    if payload == "gemini18":
        await state.clear()
        await _register_user(message)

        async with SessionLocal() as session:
            products = await repo.search_products(session, "Gemini", limit=20)

            product = next(
                (
                    p for p in products
                    if "gemini" in p.name.lower()
                    and ("18 month" in p.name.lower() or "18-month" in p.name.lower())
                ),
                None,
            )

            if product:
                local_stock = await repo.available_stock_count(session, product.id)
                available_stock = await live_stock(product.id, local_stock)

        if product:
            safe_name = escape(product.name or "")
            safe_cat = escape(product.category or "")
            safe_desc = escape(product.description or "")
            caption = (
                f"🔥 <b>{safe_name}</b>\n\n"
                f"📂 Category: <b>{safe_cat}</b>\n"
                f"⚡ Delivery: <b>Instant after confirmation</b>\n"
                f"🛡️ Support: <b>Available</b>\n"
                f"📦 Sold: <b>{product.sold_count or 0}</b>\n\n"
                f"{safe_desc}\n\n"
                f"━━━━━━━━━━━━━━\n"
                f"💵 Price: <b>${float(product.price):.2f}</b>\n"
                f"📦 Available stock: <b>{available_stock}</b>"
            )

            if available_stock <= 0:
                caption += "\n❌ <b>Currently out of stock — purchasing is disabled</b>"

            kb = product_kb(product.id, available_stock)
            sent = False
            if product.image_file_id:
                try:
                    if len(caption) <= 1024:
                        await message.answer_photo(
                            product.image_file_id,
                            caption=caption,
                            reply_markup=kb,
                            parse_mode="HTML",
                        )
                    else:
                        await message.answer_photo(product.image_file_id)
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
                        f"📂 Category: {product.category}\n"
                        f"⚡ Delivery: Instant after confirmation\n"
                        f"🛡️ Support: Available\n"
                        f"📦 Sold: {product.sold_count or 0}\n\n"
                        f"{product.description}\n\n"
                        f"━━━━━━━━━━━━━━\n"
                        f"💵 Price: ${float(product.price):.2f}\n"
                        f"📦 Available stock: {available_stock}"
                    )
                    await message.answer(plain_caption, reply_markup=kb)
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
