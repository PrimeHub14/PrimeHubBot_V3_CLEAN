import csv
import io
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db import repo
from app.db.session import SessionLocal
from app.utils.security import is_admin

router = Router()


class CsvImportFlow(StatesGroup):
    file = State()


LANGUAGES = {"en": "English", "pt": "Português", "hi": "हिन्दी"}


@router.message(Command("coupon"))
async def coupon_command(message: Message):
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("Usage: /coupon CODE")
        return
    async with SessionLocal() as session:
        await repo.upsert_user(session, message.from_user)
        try:
            coupon = await repo.activate_coupon_for_user(session, message.from_user.id, parts[1])
        except ValueError as exc:
            await message.answer(f"❌ {exc}")
            return
    await message.answer(f"✅ Coupon <b>{coupon.code}</b> activated: {coupon.percent_off}% off your next completed order.", parse_mode="HTML")


@router.message(Command("referral"))
async def referral_command(message: Message):
    async with SessionLocal() as session:
        await repo.upsert_user(session, message.from_user)
        code = await repo.ensure_referral_code(session, message.from_user.id)
        invited, earned = await repo.referral_stats(session, message.from_user.id)
    me = await message.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{code}"
    await message.answer(
        f"🎁 <b>Referral Program</b>\n\nYour link:\n<code>{link}</code>\n\n"
        f"Invited users: <b>{invited}</b>\nCommission earned: <b>${earned:.2f}</b>\n"
        "You earn 3% wallet credit after a referred user's delivered order.",
        parse_mode="HTML",
    )


@router.message(Command("loyalty"))
async def loyalty_command(message: Message):
    async with SessionLocal() as session:
        user = await repo.upsert_user(session, message.from_user)
    await message.answer(
        f"🏆 <b>Prime Hub Loyalty</b>\n\nPoints: <b>{int(user.loyalty_points or 0)}</b>\n"
        f"VIP tier: <b>{escape(user.vip_tier or 'Bronze')}</b>\n\n"
        "Earn 1 point for every completed USD of purchases.",
        parse_mode="HTML",
    )


@router.message(Command("vip"))
async def vip_command(message: Message):
    async with SessionLocal() as session:
        user = await repo.upsert_user(session, message.from_user)
    await message.answer(
        f"💎 <b>VIP Membership</b>\n\nCurrent tier: <b>{escape(user.vip_tier or 'Bronze')}</b>\n\n"
        "Bronze: 0–99 points\nSilver: 100–499 points\nGold: 500–999 points\nDiamond: 1000+ points",
        parse_mode="HTML",
    )


@router.message(Command("language"))
async def language_command(message: Message):
    rows = [[InlineKeyboardButton(text=name, callback_data=f"setlang:{code}")] for code, name in LANGUAGES.items()]
    await message.answer("🌍 Choose your language:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("setlang:"))
async def set_language(call: CallbackQuery):
    code = call.data.split(":")[1]
    if code not in LANGUAGES:
        return
    async with SessionLocal() as session:
        user = await repo.upsert_user(session, call.from_user)
        user.language = code
        await session.commit()
    await call.message.answer(f"✅ Language saved: {LANGUAGES[code]}. More translated screens will be added progressively.")
    await call.answer()


@router.message(Command("recommend"))
async def recommend_command(message: Message):
    async with SessionLocal() as session:
        products = await repo.recommendations(session, message.from_user.id)
        counts = await repo.stock_counts_for_products(session, [p.id for p in products])
    if not products:
        await message.answer("No recommendations available yet.")
        return
    rows = []
    for p in products:
        stock = counts.get(p.id, 0)
        rows.append([InlineKeyboardButton(
            text=f"{'✅' if stock else '❌'} {p.name} · ${float(p.price):.2f}",
            callback_data=f"product:{p.id}",
        )])
    await message.answer("🧠 <b>Recommended for You</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@router.message(Command("dashboard"))
async def dashboard_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        d = await repo.growth_dashboard(session)
        stock_rows = await repo.all_product_stock(session)
    low = sum(1 for _, available, _ in stock_rows if 0 < available <= 3)
    out = sum(1 for _, available, _ in stock_rows if available == 0)
    await message.answer(
        "📊 <b>Prime Hub Seller Dashboard</b>\n\n"
        f"Users: <b>{d['users']}</b>\nOrders: <b>{d['orders']}</b>\nDelivered: <b>{d['delivered']}</b>\n"
        f"Pending: <b>{d['pending']}</b>\nToday's revenue: <b>${d['today_revenue']:.2f}</b>\n"
        f"Total revenue: <b>${d['revenue']:.2f}</b>\nOpen tickets: <b>{d['open_tickets']}</b>\n"
        f"Active coupons: <b>{d['active_coupons']}</b>\nLow stock: <b>{low}</b>\nOut of stock: <b>{out}</b>",
        parse_mode="HTML",
    )


@router.message(Command("analytics"))
async def analytics_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        from sqlalchemy import select, func
        from app.db.models import Order, Product, User
        statuses = list((await session.execute(
            select(Order.status, func.count(Order.id)).group_by(Order.status).order_by(func.count(Order.id).desc())
        )).all())
        top = list((await session.execute(
            select(Product.name, Product.sold_count).order_by(Product.sold_count.desc()).limit(5)
        )).all())
        wallet_total = (await session.execute(select(func.coalesce(func.sum(User.wallet_balance), 0)))).scalar() or 0
    status_text = "\n".join(f"• {escape(str(s))}: {c}" for s, c in statuses) or "No orders"
    top_text = "\n".join(f"• {escape(name)}: {sold}" for name, sold in top) or "No products"
    await message.answer(
        f"📈 <b>Full Analytics</b>\n\n<b>Orders by status</b>\n{status_text}\n\n"
        f"<b>Top products</b>\n{top_text}\n\nCustomer wallet liabilities: <b>${float(wallet_total):.2f}</b>",
        parse_mode="HTML",
    )


@router.message(Command("createcoupon"))
async def create_coupon_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 5:
        await message.answer("Usage: /createcoupon CODE PERCENT MAX_USES DAYS\nExample: /createcoupon WELCOME10 10 100 30")
        return
    code, percent, max_uses, days = parts[1], int(parts[2]), int(parts[3]), int(parts[4])
    if not 1 <= percent <= 90:
        await message.answer("Percent must be between 1 and 90."); return
    expires = datetime.now(timezone.utc) + timedelta(days=days)
    async with SessionLocal() as session:
        coupon = await repo.create_coupon(session, code, percent, max_uses, expires)
    await message.answer(f"✅ Coupon {coupon.code}: {coupon.percent_off}% off, max uses {coupon.max_uses}, expires in {days} days.")


@router.message(Command("flashsale"))
async def flash_sale_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 4:
        await message.answer("Usage: /flashsale PRODUCT_ID SALE_PRICE HOURS")
        return
    product_id, price, hours = int(parts[1]), float(parts[2]), int(parts[3])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
        if not product:
            await message.answer("Product not found."); return
        sale = await repo.create_flash_sale(session, product_id, price, datetime.now(timezone.utc) + timedelta(hours=hours))
    await message.answer(f"🔥 Flash sale activated for {product.name}: ${float(sale.sale_price):.2f} for {hours} hour(s).")


@router.message(Command("importstock"))
async def import_stock_start(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /importstock PRODUCT_ID\nThen upload a CSV or TXT file with one stock item per row.")
        return
    await state.set_state(CsvImportFlow.file)
    await state.update_data(import_product_id=int(parts[1]))
    await message.answer("Upload a CSV or TXT document. The first column of every non-empty row will be added as one stock item.")


@router.message(CsvImportFlow.file)
async def import_stock_file(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if not message.document:
        await message.answer("Please upload a CSV or TXT document."); return
    data = await state.get_data()
    product_id = int(data["import_product_id"])
    file = await message.bot.get_file(message.document.file_id)
    raw = await message.bot.download_file(file.file_path)
    text = raw.read().decode("utf-8-sig", errors="replace")
    items = []
    for row in csv.reader(io.StringIO(text)):
        if row and row[0].strip() and not row[0].strip().lower() in {"stock", "item", "content"}:
            items.append(row[0].strip())
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
        if not product:
            await message.answer("Product not found."); await state.clear(); return
        added = await repo.add_stock_items(session, product_id, items)
    await state.clear()
    await message.answer(f"✅ Imported {added} stock item(s) for product #{product_id}.")
