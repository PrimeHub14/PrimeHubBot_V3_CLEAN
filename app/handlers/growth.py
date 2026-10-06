from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal
from app.services.announcements import notify_restock
from app.utils.security import is_admin

router = Router()


class CsvImportFlow(StatesGroup):
    file = State()


LANGUAGES = {"en": "English", "pt": "Português", "hi": "हिन्दी", "es": "Español", "ar": "العربية"}


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


async def render_growth_dashboard(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    d = await repo.growth_dashboard(session)
    stock_rows = await repo.all_product_stock(session)
    low = sum(1 for _, available, _ in stock_rows if 0 < available <= 3)
    out = sum(1 for _, available, _ in stock_rows if available == 0)

    inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))
    today_inr = int(round(d["today_revenue"] * inr_rate))
    total_inr = int(round(d["revenue"] * inr_rate))
    conv_rate = (d["delivered"] / d["users"] * 100) if d["users"] > 0 else 0.0

    hide_oos = await repo.get_setting_bool(session, "hide_out_of_stock", default=False)
    oos_badge = "🟢 Auto-Hidden" if hide_oos else "🔴 Visible with Badge"

    text = (
        "📊 <b>Prime Hub Fast-Growth & Sales Dashboard</b>\n\n"
        "👥 <b>Audience & Conversion:</b>\n"
        f"• Total Registered Users: <b>{d['users']}</b>\n"
        f"• Completed Orders: <b>{d['delivered']}</b>\n"
        f"• Store Conversion Rate: <b>{conv_rate:.1f}%</b>\n\n"
        "💰 <b>Revenue Performance:</b>\n"
        f"• Today's Revenue: <b>${d['today_revenue']:.2f} (~₹{today_inr:,})</b>\n"
        f"• Total Gross Revenue: <b>${d['revenue']:.2f} (~₹{total_inr:,})</b>\n\n"
        "📦 <b>Operations & Stock:</b>\n"
        f"• Pending/Processing Orders: <b>{d['pending']}</b>\n"
        f"• Open Support Tickets: <b>{d['open_tickets']}</b>\n"
        f"• Low Stock Items (≤3): <b>{low}</b>\n"
        f"• Out of Stock Items: <b>{out}</b> [{oos_badge}]\n"
        f"• Active Promo Coupons: <b>{d['active_coupons']}</b>"
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Viral Promo Tools", callback_data="admin_nav:promotools"),
                InlineKeyboardButton(text="👥 Traffic Attribution", callback_data="admin_nav:sources"),
            ],
            [
                InlineKeyboardButton(text="🔥 Hot Demand Restock", callback_data="admin_nav:hotdemand"),
                InlineKeyboardButton(text="🎯 Abandoned Orders", callback_data="admin_nav:leads"),
            ],
            [
                InlineKeyboardButton(text="📦 Out-of-Stock Manager", callback_data="admin_nav:oos"),
                InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_nav:growth_refresh"),
            ],
            [
                InlineKeyboardButton(text="🔙 Admin Panel", callback_data="admin_nav:main"),
            ],
        ]
    )
    return text, kb


def render_promotools_view() -> tuple[str, InlineKeyboardMarkup]:
    bot_user = getattr(settings, "TELEGRAM_BOT_USERNAME", "PrimeHubUs_Bot")
    text = (
        "🚀 <b>Prime Hub Fast-Growth Marketing Toolkit</b>\n\n"
        "Share these trackable campaign links on your channels to see which channel brings the most buyers:\n\n"
        "🔗 <b>1. Your Trackable Links:</b>\n"
        f"• 📱 <b>WhatsApp Groups/Chats:</b>\n<code>https://t.me/{bot_user}?start=promo_wa</code>\n\n"
        f"• 📢 <b>Telegram Channel Shoutouts:</b>\n<code>https://t.me/{bot_user}?start=promo_tg</code>\n\n"
        f"• 🚀 <b>Telegram Ads / Meta Ads:</b>\n<code>https://t.me/{bot_user}?start=promo_ads</code>\n\n"
        f"• 💬 <b>WhatsApp Status / Stories:</b>\n<code>https://t.me/{bot_user}?start=promo_status</code>\n\n"
        "📝 <b>2. Copy-Paste High-Converting Post Templates:</b>\n"
        "Tap below to instantly get ready-to-post messages with pricing, emojis & links:"
    )
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚡ Flash Sale Template", callback_data="admin_promo:flash"),
                InlineKeyboardButton(text="🎁 Gemini AI Special Offer", callback_data="admin_promo:gemini"),
            ],
            [
                InlineKeyboardButton(text="🔔 Restock Alert Template", callback_data="admin_promo:restock"),
                InlineKeyboardButton(text="⭐ Reviews & Proof Post", callback_data="admin_promo:proof"),
            ],
            [
                InlineKeyboardButton(text="🔙 Growth Dashboard", callback_data="admin_nav:growth"),
                InlineKeyboardButton(text="🔙 Admin Menu", callback_data="admin_nav:main"),
            ],
        ]
    )
    return text, kb


async def render_traffic_sources_view(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    sources = await repo.get_traffic_source_stats(session)
    inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))

    text = "👥 <b>Traffic Source & Acquisition Attribution</b>\n\n"
    if not sources:
        text += "<i>No acquisition data recorded yet. Share your trackable links from /promotools to start tracking!</i>\n"
    else:
        text += "Here is how each marketing channel is performing:\n\n"
        for s in sources:
            src_name = s["source"]
            u = s["users"]
            o = s["orders"]
            rev = s["revenue"]
            rev_inr = int(round(rev * inr_rate))
            c_rate = (o / u * 100) if u > 0 else 0.0
            icon = "📱" if "wa" in src_name.lower() else ("📢" if "tg" in src_name.lower() else ("🚀" if "ad" in src_name.lower() else "🌐"))
            text += (
                f"{icon} <b>{escape(src_name)}</b>\n"
                f"   • Users: <b>{u}</b> | Orders: <b>{o}</b> ({c_rate:.1f}% conv)\n"
                f"   • Revenue: <b>${rev:.2f} (~₹{rev_inr:,})</b>\n\n"
            )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🚀 Get Promo Links", callback_data="admin_nav:promotools"),
                InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_nav:sources_refresh"),
            ],
            [
                InlineKeyboardButton(text="🔙 Growth Dashboard", callback_data="admin_nav:growth"),
                InlineKeyboardButton(text="🔙 Admin Menu", callback_data="admin_nav:main"),
            ],
        ]
    )
    return text, kb


async def render_hotdemand_view(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    demands = await repo.get_hottest_out_of_stock_demands(session)
    from app.handlers.user import product_stock_map
    all_products = await repo.list_products(session, only_active=False)
    stock_map = await product_stock_map(session, all_products)

    text = "🔥 <b>High-Demand Restock Radar</b>\n\n"
    text += "These are the products customers are actively waiting for (clicked <i>'Notify Me on Restock'</i>):\n\n"

    rows = []
    found = False
    for item in demands:
        p = item["product"]
        sub_count = item["subscribers"]
        stk = int(stock_map.get(p.id, 0))
        if stk == 0:
            found = True
            text += f"• 🔴 <b>{escape(p.name)}</b> (ID #{p.id})\n  ↳ <b>{sub_count} customers waiting</b> · Price: ${float(p.price):.2f}\n\n"
            rows.append([
                InlineKeyboardButton(text=f"➕ Add Stock #{p.id}", callback_data=f"admin_oos:addstock:{p.id}")
            ])

    if not found:
        text += "🎉 <i>No out-of-stock items have pending restock waitlists right now!</i>\n"

    rows.append([
        InlineKeyboardButton(text="📦 Out-of-Stock Manager", callback_data="admin_nav:oos"),
        InlineKeyboardButton(text="🔙 Growth Dashboard", callback_data="admin_nav:growth"),
    ])
    rows.append([
        InlineKeyboardButton(text="🔙 Admin Menu", callback_data="admin_nav:main"),
    ])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def render_abandoned_leads_view(session: AsyncSession) -> tuple[str, InlineKeyboardMarkup]:
    orders = await repo.get_abandoned_orders(session, hours=24)
    inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))

    total_pending_val = sum(float(o.amount) for o in orders)
    val_inr = int(round(total_pending_val * inr_rate))

    text = (
        "🎯 <b>Lead & Abandoned Checkout Recovery</b>\n\n"
        f"• Pending/Unpaid Orders (last 24h): <b>{len(orders)}</b>\n"
        f"• Potential Revenue on Table: <b>${total_pending_val:.2f} (~₹{val_inr:,})</b>\n\n"
    )
    if orders:
        text += "<b>Recent Pending Leads:</b>\n"
        for o in orders[:8]:
            dt = o.created_at.strftime("%H:%M") if o.created_at else ""
            p_name = o.product.name if o.product else f"Item #{o.product_id}"
            text += f"• Order #{o.id} · {escape(p_name[:20])} · ${float(o.amount):.2f} ({dt})\n"
        if len(orders) > 8:
            text += f"<i>...and {len(orders) - 8} more leads.</i>\n"
        text += "\n💡 <i>Automated Meta/Gemini follow-up runs in background. You can inspect any order using /order ORDER_ID.</i>"
    else:
        text += "🎉 <i>No abandoned orders in the last 24 hours!</i>"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 View All Orders", callback_data="admin_nav:orders"),
                InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_nav:leads_refresh"),
            ],
            [
                InlineKeyboardButton(text="🔙 Growth Dashboard", callback_data="admin_nav:growth"),
                InlineKeyboardButton(text="🔙 Admin Menu", callback_data="admin_nav:main"),
            ],
        ]
    )
    return text, kb


@router.message(Command("dashboard", "growth"))
async def dashboard_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        text, kb = await render_growth_dashboard(session)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("promotools", "grow"))
async def promotools_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    text, kb = render_promotools_view()
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("attribution", "sources"))
async def attribution_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        text, kb = await render_traffic_sources_view(session)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("hotdemand"))
async def hotdemand_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        text, kb = await render_hotdemand_view(session)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.message(Command("leads", "abandoned"))
async def leads_command(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        text, kb = await render_abandoned_leads_view(session)
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin_nav:growth")
async def cb_nav_growth(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    async with SessionLocal() as session:
        text, kb = await render_growth_dashboard(session)
    await call.answer()
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin_nav:growth_refresh")
async def cb_nav_growth_refresh(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    async with SessionLocal() as session:
        text, kb = await render_growth_dashboard(session)
    await call.answer("🔄 Dashboard refreshed!")
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data == "admin_nav:promotools")
async def cb_nav_promotools(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    text, kb = render_promotools_view()
    await call.answer()
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin_nav:sources")
async def cb_nav_sources(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    async with SessionLocal() as session:
        text, kb = await render_traffic_sources_view(session)
    await call.answer()
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin_nav:sources_refresh")
async def cb_nav_sources_refresh(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    async with SessionLocal() as session:
        text, kb = await render_traffic_sources_view(session)
    await call.answer("🔄 Traffic sources refreshed!")
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data == "admin_nav:hotdemand")
async def cb_nav_hotdemand(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    async with SessionLocal() as session:
        text, kb = await render_hotdemand_view(session)
    await call.answer()
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin_nav:leads")
async def cb_nav_leads(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    async with SessionLocal() as session:
        text, kb = await render_abandoned_leads_view(session)
    await call.answer()
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await call.message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "admin_nav:leads_refresh")
async def cb_nav_leads_refresh(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    async with SessionLocal() as session:
        text, kb = await render_abandoned_leads_view(session)
    await call.answer("🔄 Leads refreshed!")
    try:
        await call.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data == "admin_promo:flash")
async def cb_promo_flash(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    bot_user = getattr(settings, "TELEGRAM_BOT_USERNAME", "PrimeHubUs_Bot")
    await call.answer("⚡ Template generated!")
    post = (
        "🔥 <b>FLASH SALE ALERT — 24 HOURS ONLY!</b> 🔥\n\n"
        "Get top premium tools & subscriptions at wholesale rates:\n\n"
        "✨ <b>Gemini AI Pro 18 Months + 5TB:</b> ₹149 only!\n"
        "✨ <b>Spotify Premium 2 Months:</b> ₹59\n"
        "✨ <b>Apple Music 5 Months:</b> ₹215\n"
        "✨ <b>Coursera Premium 12 Months:</b> ₹470\n"
        "✨ <b>Adobe Express 12 Months:</b> ₹250\n\n"
        "⚡ <i>Instant automated delivery in seconds!</i>\n"
        "🛡️ <i>1-Month Replacement Warranty included</i>\n"
        "💳 <i>Pay easily via UPI (GPay, PhonePe, Paytm) or Crypto</i>\n\n"
        f"👉 <b>BUY NOW ON BOT:</b>\n"
        f"https://t.me/{bot_user}?start=promo_wa\n\n"
        "__Team Prime Hub"
    )
    await call.message.answer(f"📋 <b>Copy & Paste Flash Sale Post:</b>\n\n{post}", parse_mode="HTML")


@router.callback_query(F.data == "admin_promo:gemini")
async def cb_promo_gemini(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    bot_user = getattr(settings, "TELEGRAM_BOT_USERNAME", "PrimeHubUs_Bot")
    await call.answer("🎁 Template generated!")
    post = (
        "💙 <b>Special Limited Offer ✨️</b>\n\n"
        "Get <b>Gemini AI Pro 18 Months</b>\n"
        "just <b>₹149/- Only</b>\n\n"
        "📦 <b>Included in Plan:</b>\n"
        "• 5TB Cloud Storage (Google Drive + Gmail + Photos)\n"
        "• Gemini Advanced AI Access & Deep Reasoning\n"
        "• Antigravity & NotebookLM\n"
        "• Add up to 5 family members\n"
        "• Activates on your own Google email!\n\n"
        "<i>Note: Limited slots available tonight, claim before it's gone.</i>\n\n"
        f"Telegram Bot Store: @{bot_user}\n"
        f"👉 https://t.me/{bot_user}?start=gemini\n\n"
        "__Team Prime Hub"
    )
    await call.message.answer(f"📋 <b>Copy & Paste Gemini Offer:</b>\n\n{post}", parse_mode="HTML")


@router.callback_query(F.data == "admin_promo:restock")
async def cb_promo_restock(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    bot_user = getattr(settings, "TELEGRAM_BOT_USERNAME", "PrimeHubUs_Bot")
    await call.answer("🔔 Template generated!")
    post = (
        "📦 <b>FRESH STOCK ALERT! 🎉</b>\n\n"
        "We just restocked high-demand subscriptions on Prime Hub:\n"
        "✅ Instant delivery is LIVE\n"
        "✅ 100% verified credentials & replacement warranty\n\n"
        "Visit the bot now to grab your plan before stock runs out:\n"
        f"👉 https://t.me/{bot_user}?start=promo_tg\n\n"
        "__Team Prime Hub"
    )
    await call.message.answer(f"📋 <b>Copy & Paste Restock Alert:</b>\n\n{post}", parse_mode="HTML")


@router.callback_query(F.data == "admin_promo:proof")
async def cb_promo_proof(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    bot_user = getattr(settings, "TELEGRAM_BOT_USERNAME", "PrimeHubUs_Bot")
    await call.answer("⭐ Template generated!")
    post = (
        "⭐ <b>PRIME HUB STORE — 100% TRUSTED & INSTANT</b> ⭐\n\n"
        "• Hundreds of satisfied customers served!\n"
        "• Instant automated delivery directly in chat\n"
        "• 24/7 dedicated replacement warranty & friendly support\n\n"
        "Start shopping top subscriptions with the best wholesale rates in India:\n"
        f"👉 https://t.me/{bot_user}?start=promo_wa\n\n"
        "__Team Prime Hub"
    )
    await call.message.answer(f"📋 <b>Copy & Paste Trust & Reviews Post:</b>\n\n{post}", parse_mode="HTML")



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
        await message.answer("Please upload a CSV or TXT document.")
        return
    data = await state.get_data()
    product_id = int(data["import_product_id"])
    file = await message.bot.get_file(message.document.file_id)
    raw = await message.bot.download_file(file.file_path)
    raw_bytes = raw.read() if hasattr(raw, "read") else raw
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1", errors="replace")

    items = []
    file_name = (message.document.file_name or "").lower()
    if file_name.endswith(".csv"):
        for row in csv.reader(io.StringIO(text)):
            if row and row[0].strip() and not row[0].strip().lower() in {"stock", "item", "content", "link", "links", "url"}:
                items.append(row[0].strip())
    else:
        for line in text.splitlines():
            val = line.strip()
            if val and not val.lower() in {"stock", "item", "content", "link", "links", "url"}:
                items.append(val)

    if not items:
        await message.answer("❌ No valid stock items found in the document.")
        return

    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
        if not product:
            await message.answer("Product not found.")
            await state.clear()
            return
        added = await repo.add_stock_items(session, product_id, items)
        total = await repo.available_stock_count(session, product_id)

    await state.clear()
    await message.answer(
        f"✅ <b>Imported {added} stock item(s)</b> for <b>{escape(product.name)}</b> (ID #{product_id}).\n"
        f"📦 <b>Available stock now:</b> {total}",
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
        except Exception:
            pass
