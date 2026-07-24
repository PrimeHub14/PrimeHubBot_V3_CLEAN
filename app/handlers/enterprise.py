from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db import repo
from app.db.session import SessionLocal
from app.i18n import LANGUAGE_NAMES, tr
from app.keyboards import main_menu_kb, product_list_kb
from app.utils.security import is_admin

router = Router()

class SearchFlow(StatesGroup):
    query = State()

class BroadcastFlow(StatesGroup):
    message = State()

def language_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"v5:setlang:{code}")]
        for code, name in LANGUAGE_NAMES.items()
    ])

def admin_dashboard_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Sales & Reports", callback_data="v5admin:sales"),
         InlineKeyboardButton(text="📦 Inventory", callback_data="v5admin:inventory")],
        [InlineKeyboardButton(text="👥 Customers", callback_data="v5admin:customers"),
         InlineKeyboardButton(text="🏪 Products", callback_data="v5admin:products")],
        [InlineKeyboardButton(text="🎟 Coupons", callback_data="v5admin:coupons"),
         InlineKeyboardButton(text="🔥 Flash Sales", callback_data="v5admin:flash")],
        [InlineKeyboardButton(text="📢 Marketing", callback_data="v5admin:marketing"),
         InlineKeyboardButton(text="🎫 Support", callback_data="v5admin:support")],
        [InlineKeyboardButton(text="🤖 AI", callback_data="v5admin:ai"),
         InlineKeyboardButton(text="📈 Analytics", callback_data="v5admin:analytics")],
        [InlineKeyboardButton(text="🧾 Audit Log", callback_data="v5admin:audit"),
         InlineKeyboardButton(text="⚙ Settings", callback_data="v5admin:settings")],
    ])

@router.message(Command("enterprise", "v5"))
async def enterprise_dashboard(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        d = await repo.growth_dashboard(session)
        inv = await repo.inventory_enterprise_summary(session)
    await message.answer(
        "💎 <b>Prime Hub V5 Enterprise</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 Today: <b>${d['today_revenue']:.2f}</b>\n"
        f"📦 Orders: <b>{d['orders']}</b> · Pending: <b>{d['pending']}</b>\n"
        f"👥 Customers: <b>{d['users']}</b>\n"
        f"🎫 Open tickets: <b>{d['open_tickets']}</b>\n"
        f"⚠️ Low stock: <b>{inv['low']}</b> · Out: <b>{inv['out']}</b>\n"
        "━━━━━━━━━━━━━━━━━━\nChoose a management area:",
        reply_markup=admin_dashboard_kb(), parse_mode="HTML"
    )

@router.callback_query(F.data == "v5:language")
async def choose_language(call: CallbackQuery):
    async with SessionLocal() as session:
        user = await repo.upsert_user(session, call.from_user)
    await call.message.answer(tr(user.language, "choose_language"), reply_markup=language_kb())
    await call.answer()

@router.callback_query(F.data.startswith("v5:setlang:"))
async def set_language(call: CallbackQuery):
    lang = call.data.rsplit(":",1)[1]
    if lang not in LANGUAGE_NAMES:
        await call.answer("Unsupported language.", show_alert=True); return
    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        await repo.set_user_language(session, call.from_user.id, lang)
    await call.message.answer(f"✅ {tr(lang,'saved')}", reply_markup=main_menu_kb(lang))
    await call.answer()

@router.callback_query(F.data == "v5:profile")
async def profile(call: CallbackQuery):
    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        m = await repo.user_profile_metrics(session, call.from_user.id)
    username = f"@{call.from_user.username}" if call.from_user.username else "Not set"
    await call.message.answer(
        "👤 <b>Prime Hub Profile</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Name: <b>{escape(call.from_user.full_name)}</b>\nUsername: <b>{escape(username)}</b>\n"
        f"Telegram ID: <code>{call.from_user.id}</code>\n\n"
        f"💰 Wallet: <b>${m['wallet']:.2f}</b>\n📦 Orders: <b>{m['orders']}</b> · Completed: <b>{m['paid_orders']}</b>\n"
        f"💵 Lifetime spent: <b>${m['spent']:.2f}</b>\n🏆 Points: <b>{m['points']}</b>\n"
        f"💎 VIP: <b>{escape(m['vip'])}</b>\n❤️ Wishlist: <b>{m['wishlist']}</b>\n"
        f"👥 Referrals: <b>{m['referrals']}</b>\n🎁 Referral earnings: <b>${m['referral_earned']:.2f}</b>",
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "v5:rewards")
async def rewards(call: CallbackQuery):
    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        code = await repo.ensure_referral_code(session, call.from_user.id)
        m = await repo.user_profile_metrics(session, call.from_user.id)
    me = await call.bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{code}"
    await call.message.answer(
        "🎁 <b>Prime Rewards Center</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Points: <b>{m['points']}</b>\n💎 VIP: <b>{escape(m['vip'])}</b>\n"
        f"👥 Referrals: <b>{m['referrals']}</b>\n💰 Earnings: <b>${m['referral_earned']:.2f}</b>\n\n"
        f"Referral link:\n<code>{link}</code>\n\nUse /coupon CODE to activate a coupon.",
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "v5:vip")
async def vip(call: CallbackQuery):
    async with SessionLocal() as session:
        m = await repo.user_profile_metrics(session, call.from_user.id)
    await call.message.answer(
        "💎 <b>Prime Hub VIP</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"Current tier: <b>{escape(m['vip'])}</b>\nPoints: <b>{m['points']}</b>\n\n"
        "🥉 Bronze · 0–99\n🥈 Silver · 100–499\n🥇 Gold · 500–999\n💎 Diamond · 1000+",
        parse_mode="HTML"
    )
    await call.answer()

@router.callback_query(F.data == "v5:search")
async def search_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(SearchFlow.query)
    await call.message.answer("🔎 <b>Search Prime Hub</b>\n\nType a product name, category, or keyword.", parse_mode="HTML")
    await call.answer()

@router.message(SearchFlow.query)
async def search_query(message: Message, state: FSMContext):
    query = (message.text or "").strip()
    if not query:
        await message.answer("Type a search keyword."); return
    async with SessionLocal() as session:
        products = await repo.search_products(session, query)
        counts = await repo.stock_counts_for_products(session, [p.id for p in products])
    await state.clear()
    if not products:
        await message.answer(f"🔎 No products found for <b>{escape(query)}</b>.", parse_mode="HTML"); return
    await message.answer(f"🔎 <b>Search: {escape(query)}</b>", reply_markup=product_list_kb(products, counts), parse_mode="HTML")

@router.callback_query(F.data.startswith("v5:wishlisttoggle:"))
async def wishlist_toggle(call: CallbackQuery):
    product_id = int(call.data.rsplit(":",1)[1])
    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        added = await repo.toggle_wishlist(session, call.from_user.id, product_id)
    await call.answer("Added to wishlist ❤️" if added else "Removed from wishlist.", show_alert=True)

@router.callback_query(F.data == "v5:wishlist")
async def wishlist(call: CallbackQuery):
    async with SessionLocal() as session:
        products = await repo.wishlist_products(session, call.from_user.id)
        counts = await repo.stock_counts_for_products(session, [p.id for p in products])
    if not products:
        await call.message.answer("❤️ <b>Your Wishlist</b>\n\nNo saved products yet.", parse_mode="HTML")
    else:
        await call.message.answer("❤️ <b>Your Wishlist</b>", reply_markup=product_list_kb(products, counts), parse_mode="HTML")
    await call.answer()

@router.callback_query(F.data.startswith("v5:reviews:"))
async def product_reviews(call: CallbackQuery):
    product_id = int(call.data.rsplit(":",1)[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
        avg, count = await repo.product_review_summary(session, product_id)
        reviews = await repo.recent_product_reviews(session, product_id)
    if not product:
        await call.answer("Product not found.", show_alert=True); return
    lines = [f"⭐ <b>Reviews — {escape(product.name)}</b>", "", f"Rating: <b>{avg:.1f}/5</b> · {count} review(s)"]
    for review, user in reviews:
        lines.append(f"\n{'⭐'*review.rating} <b>{escape(user.first_name or 'Customer')}</b>\n{escape(review.comment or 'No comment')}")
    lines.append("\nReview a delivered order:\n<code>/review ORDER_ID RATING comment</code>")
    await call.message.answer("\n".join(lines), parse_mode="HTML")
    await call.answer()

@router.message(Command("review"))
async def review_command(message: Message):
    parts = (message.text or "").split(maxsplit=3)
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Usage: /review ORDER_ID RATING comment"); return
    rating = int(parts[2])
    if rating < 1 or rating > 5:
        await message.answer("Rating must be 1 to 5."); return
    async with SessionLocal() as session:
        try:
            review = await repo.create_product_review(session, message.from_user.id, int(parts[1]), rating, parts[3] if len(parts)>3 else "")
        except ValueError as exc:
            await message.answer(f"❌ {exc}"); return
    await message.answer(f"✅ Review submitted: {'⭐'*review.rating}")

@router.message(Command("recent"))
async def recently_viewed(message: Message):
    async with SessionLocal() as session:
        products = await repo.recently_viewed_products(session, message.from_user.id)
        counts = await repo.stock_counts_for_products(session, [p.id for p in products])
    if not products:
        await message.answer("No recently viewed products yet."); return
    await message.answer("🕘 <b>Recently Viewed</b>", reply_markup=product_list_kb(products, counts), parse_mode="HTML")

@router.callback_query(F.data.startswith("v5admin:"))
async def admin_section(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    section = call.data.split(":",1)[1]
    async with SessionLocal() as session:
        if section == "inventory":
            inv = await repo.inventory_enterprise_summary(session)
            lines = ["📦 <b>Enterprise Inventory</b>","━━━━━━━━━━━━━━━━━━",
                     f"Live stock: <b>{inv['total_stock']}</b>",f"Low: <b>{inv['low']}</b>",f"Out: <b>{inv['out']}</b>",""]
            for product, available in inv["rows"][:20]:
                dot = "🔴" if available == 0 else "🟡" if available <= 3 else "🟢"
                lines.append(f"{dot} #{product.id} {escape(product.name)} · {available} · Sold {product.sold_count or 0}")
            await call.message.answer("\n".join(lines), parse_mode="HTML")
        elif section == "products":
            await call.message.answer("🏪 <b>Product Center</b>\n\n/addproduct\n/listproducts\n/moveproduct PRODUCT_ID\n/importstock PRODUCT_ID\n/stock", parse_mode="HTML")
        elif section == "coupons":
            await call.message.answer("🎟 <b>Coupon Center</b>\n\n<code>/createcoupon CODE PERCENT MAX_USES DAYS</code>", parse_mode="HTML")
        elif section == "flash":
            await call.message.answer("🔥 <b>Flash Sales</b>\n\n<code>/flashsale PRODUCT_ID SALE_PRICE HOURS</code>", parse_mode="HTML")
        elif section == "marketing":
            await call.message.answer("📢 <b>Marketing Center</b>\n\n/broadcast\n/schedulebroadcast\n/announce", parse_mode="HTML")
        elif section == "support":
            await call.message.answer("🎫 <b>Support Center</b>\n\nUse /ticketsadmin.", parse_mode="HTML")
        elif section == "ai":
            await call.message.answer("🤖 <b>AI Center</b>\n\nUse /assistant.", parse_mode="HTML")
        elif section in {"sales","analytics"}:
            await call.message.answer("📈 <b>Analytics Center</b>\n\nUse /reports.", parse_mode="HTML")
        elif section == "audit":
            logs = await repo.recent_audit_logs(session)
            lines = ["🧾 <b>Admin Audit Log</b>",""]
            for item in logs:
                lines.append(f"#{item.id} · {escape(item.action)} · Admin {item.admin_id}\n{escape(item.details)}")
            await call.message.answer("\n".join(lines) if logs else "No audit logs yet.", parse_mode="HTML")
        elif section == "customers":
            d = await repo.growth_dashboard(session)
            await call.message.answer(f"👥 <b>Customer Center</b>\n\nTotal users: <b>{d['users']}</b>\nUse /reports → Customer Performance.", parse_mode="HTML")
        else:
            await call.message.answer("⚙ <b>Enterprise Settings</b>\n\nLanguages: English, Portuguese, Hindi, Spanish, Arabic.", parse_mode="HTML")
    await call.answer()

@router.message(Command("broadcast"))
async def broadcast_start(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id): return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Everyone",callback_data="v5broadcast:all")],
        [InlineKeyboardButton(text="💎 VIP",callback_data="v5broadcast:vip")],
        [InlineKeyboardButton(text="🛍 Previous Buyers",callback_data="v5broadcast:buyers")],
        [InlineKeyboardButton(text="🎁 Referral Users",callback_data="v5broadcast:referrers")],
    ])
    await message.answer("📢 Choose broadcast audience:", reply_markup=kb)

@router.callback_query(F.data.startswith("v5broadcast:"))
async def broadcast_audience(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id): return
    await state.update_data(v5_broadcast_audience=call.data.split(":",1)[1])
    await state.set_state(BroadcastFlow.message)
    await call.message.answer("Send the broadcast text now.")
    await call.answer()

@router.message(BroadcastFlow.message)
async def broadcast_send(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id): return
    data = await state.get_data()
    content = (message.text or "").strip()
    if not content: await message.answer("Send text."); return
    async with SessionLocal() as session:
        ids = await repo.audience_user_ids(session, data.get("v5_broadcast_audience","all"))
        await repo.audit_log(session, message.from_user.id, "broadcast", f"Recipients={len(ids)}")
    sent=failed=0
    for uid in ids:
        try:
            await message.bot.send_message(uid, f"📢 <b>Prime Hub Update</b>\n\n{escape(content)}", parse_mode="HTML"); sent+=1
        except Exception: failed+=1
        await asyncio.sleep(0.035)
    await state.clear()
    await message.answer(f"✅ Broadcast complete. Sent: {sent} · Failed: {failed}")

@router.message(Command("schedulebroadcast"))
async def schedule_broadcast_command(message: Message):
    if not message.from_user or not is_admin(message.from_user.id): return
    parts=(message.text or "").split(maxsplit=4)
    if len(parts)<5:
        await message.answer("Usage: /schedulebroadcast YYYY-MM-DD HH:MM AUDIENCE message\nAudience: all, vip, buyers, referrers\nTime: UTC"); return
    try:
        when=datetime.strptime(f"{parts[1]} {parts[2]}","%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
    except ValueError:
        await message.answer("Invalid date/time."); return
    if parts[3] not in {"all","vip","buyers","referrers"}:
        await message.answer("Invalid audience."); return
    async with SessionLocal() as session:
        item=await repo.schedule_broadcast(session,parts[3],parts[4],when)
        await repo.audit_log(session,message.from_user.id,"schedule_broadcast",f"#{item.id}")
    await message.answer(f"✅ Broadcast #{item.id} scheduled for {when.strftime('%d %b %Y %H:%M UTC')}.")

async def scheduled_broadcast_worker(bot):
    while True:
        try:
            async with SessionLocal() as session:
                for item in await repo.due_broadcasts(session):
                    item.status="sending"; await session.commit()
                    ids=await repo.audience_user_ids(session,item.audience)
                    sent=failed=0
                    for uid in ids:
                        try:
                            await bot.send_message(uid,f"📢 <b>Prime Hub Update</b>\n\n{escape(item.message)}",parse_mode="HTML"); sent+=1
                        except Exception: failed+=1
                        await asyncio.sleep(0.035)
                    item.sent_count=sent; item.failed_count=failed; item.status="sent"; await session.commit()
        except Exception:
            pass
        await asyncio.sleep(60)
