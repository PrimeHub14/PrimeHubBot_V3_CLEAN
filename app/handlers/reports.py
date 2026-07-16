from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import func, select

from app.db.models import Order, Product, User
from app.db.session import SessionLocal
from app.utils.security import is_admin

router = Router()


class CustomReportFlow(StatesGroup):
    dates = State()


PAID_STATUSES = {"delivered", "manual_pending", "paid", "completed"}


def report_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Today", callback_data="report:today"),
                InlineKeyboardButton(text="🕘 Yesterday", callback_data="report:yesterday"),
            ],
            [
                InlineKeyboardButton(text="📆 Last 7 Days", callback_data="report:7d"),
                InlineKeyboardButton(text="🗓 Last 30 Days", callback_data="report:30d"),
            ],
            [
                InlineKeyboardButton(text="📊 Last 1 Year", callback_data="report:365d"),
                InlineKeyboardButton(text="✏️ Custom Dates", callback_data="report:custom"),
            ],
            [
                InlineKeyboardButton(text="🏆 Product Performance", callback_data="report:products"),
                InlineKeyboardButton(text="👥 Customer Performance", callback_data="report:customers"),
            ],
            [InlineKeyboardButton(text="🏠 Close", callback_data="report:close")],
        ]
    )


def utc_day_start(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def period_for(key: str) -> tuple[datetime, datetime, str]:
    now = datetime.now(timezone.utc)
    today = utc_day_start(now)
    if key == "today":
        return today, now, "Today"
    if key == "yesterday":
        start = today - timedelta(days=1)
        return start, today, "Yesterday"
    if key == "7d":
        return today - timedelta(days=6), now, "Last 7 Days"
    if key == "30d":
        return today - timedelta(days=29), now, "Last 30 Days"
    if key == "365d":
        return today - timedelta(days=364), now, "Last 1 Year"
    raise ValueError("Unknown report period")


async def build_sales_report(start: datetime, end: datetime, label: str) -> str:
    async with SessionLocal() as session:
        base = [Order.created_at >= start, Order.created_at < end]

        total_orders = (
            await session.execute(select(func.count(Order.id)).where(*base))
        ).scalar() or 0
        paid_orders = (
            await session.execute(
                select(func.count(Order.id)).where(*base, Order.status.in_(PAID_STATUSES))
            )
        ).scalar() or 0
        revenue = (
            await session.execute(
                select(func.coalesce(func.sum(Order.amount), 0)).where(
                    *base, Order.status.in_(PAID_STATUSES)
                )
            )
        ).scalar() or 0
        total_units = (
            await session.execute(
                select(func.coalesce(func.sum(Order.quantity), 0)).where(
                    *base, Order.status.in_(PAID_STATUSES)
                )
            )
        ).scalar() or 0
        unique_buyers = (
            await session.execute(
                select(func.count(func.distinct(Order.user_id))).where(
                    *base, Order.status.in_(PAID_STATUSES)
                )
            )
        ).scalar() or 0
        cancelled = (
            await session.execute(
                select(func.count(Order.id)).where(
                    *base, Order.status.in_(["cancelled", "expired", "rejected"])
                )
            )
        ).scalar() or 0
        pending = (
            await session.execute(
                select(func.count(Order.id)).where(
                    *base,
                    Order.status.in_(["pending", "awaiting_proof", "proof_submitted", "waiting_payment"]),
                )
            )
        ).scalar() or 0

        avg_order = float(revenue) / int(paid_orders) if paid_orders else 0.0
        conversion = (int(paid_orders) / int(total_orders) * 100) if total_orders else 0.0

        top_products = list(
            (
                await session.execute(
                    select(
                        Product.name,
                        func.sum(Order.quantity).label("units"),
                        func.sum(Order.amount).label("revenue"),
                    )
                    .join(Order, Order.product_id == Product.id)
                    .where(*base, Order.status.in_(PAID_STATUSES))
                    .group_by(Product.id, Product.name)
                    .order_by(func.sum(Order.amount).desc())
                    .limit(5)
                )
            ).all()
        )

    lines = [
        f"📊 <b>Sales Report — {escape(label)}</b>",
        "",
        f"Period: <b>{start.strftime('%d %b %Y')}</b> to <b>{end.strftime('%d %b %Y')}</b>",
        "",
        f"💰 Revenue: <b>${float(revenue):.2f}</b>",
        f"✅ Paid orders: <b>{int(paid_orders)}</b>",
        f"🧾 Total orders created: <b>{int(total_orders)}</b>",
        f"📦 Units sold: <b>{int(total_units)}</b>",
        f"👥 Unique buyers: <b>{int(unique_buyers)}</b>",
        f"💳 Average order value: <b>${avg_order:.2f}</b>",
        f"📈 Payment conversion: <b>{conversion:.1f}%</b>",
        f"⏳ Pending: <b>{int(pending)}</b>",
        f"❌ Cancelled / expired / rejected: <b>{int(cancelled)}</b>",
    ]

    if top_products:
        lines += ["", "🏆 <b>Top Products</b>"]
        for name, units, product_revenue in top_products:
            lines.append(
                f"• {escape(name)} — {int(units or 0)} units — ${float(product_revenue or 0):.2f}"
            )
    return "\n".join(lines)


async def build_product_performance() -> str:
    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(
                        Product.name,
                        func.count(Order.id).label("orders"),
                        func.coalesce(func.sum(Order.quantity), 0).label("units"),
                        func.coalesce(func.sum(Order.amount), 0).label("revenue"),
                    )
                    .outerjoin(
                        Order,
                        (Order.product_id == Product.id)
                        & (Order.status.in_(PAID_STATUSES)),
                    )
                    .group_by(Product.id, Product.name)
                    .order_by(func.coalesce(func.sum(Order.amount), 0).desc())
                    .limit(20)
                )
            ).all()
        )

    lines = ["🏆 <b>Product Performance</b>", ""]
    if not rows:
        return "\n".join(lines + ["No sales data yet."])
    for index, (name, orders, units, revenue) in enumerate(rows, start=1):
        lines.append(
            f"{index}. <b>{escape(name)}</b>\n"
            f"   Orders: {int(orders or 0)} · Units: {int(units or 0)} · Revenue: ${float(revenue or 0):.2f}"
        )
    return "\n".join(lines)


async def build_customer_performance() -> str:
    async with SessionLocal() as session:
        rows = list(
            (
                await session.execute(
                    select(
                        User.id,
                        User.first_name,
                        User.username,
                        func.count(Order.id).label("orders"),
                        func.coalesce(func.sum(Order.amount), 0).label("spent"),
                    )
                    .join(
                        Order,
                        (Order.user_id == User.id)
                        & (Order.status.in_(PAID_STATUSES)),
                    )
                    .group_by(User.id, User.first_name, User.username)
                    .order_by(func.sum(Order.amount).desc())
                    .limit(20)
                )
            ).all()
        )

    lines = ["👥 <b>Customer Performance</b>", ""]
    if not rows:
        return "\n".join(lines + ["No customer sales data yet."])
    for index, (user_id, first_name, username, orders, spent) in enumerate(rows, start=1):
        display = first_name or "Customer"
        if username:
            display += f" (@{username})"
        lines.append(
            f"{index}. <b>{escape(display)}</b>\n"
            f"   Telegram ID: <code>{user_id}</code> · Orders: {int(orders or 0)} · Spent: ${float(spent or 0):.2f}"
        )
    return "\n".join(lines)


@router.message(Command("reports", "salesreport"))
async def reports_command(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "📊 <b>Prime Hub Reports</b>\n\nChoose a time period or performance report:",
        reply_markup=report_menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("report:"))
async def report_callback(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return

    key = call.data.split(":", 1)[1]

    if key == "close":
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer()
        return

    if key == "custom":
        await state.set_state(CustomReportFlow.dates)
        await call.message.answer(
            "✏️ Send the custom date range in this format:\n"
            "<code>2026-07-01 2026-07-16</code>\n\n"
            "The first date is included. The second date includes the full day.",
            parse_mode="HTML",
        )
        await call.answer()
        return

    if key == "products":
        await call.message.answer(await build_product_performance(), parse_mode="HTML")
        await call.answer()
        return

    if key == "customers":
        await call.message.answer(await build_customer_performance(), parse_mode="HTML")
        await call.answer()
        return

    try:
        start, end, label = period_for(key)
    except ValueError:
        await call.answer("Invalid report period.", show_alert=True)
        return

    await call.message.answer(
        await build_sales_report(start, end, label),
        reply_markup=report_menu(),
        parse_mode="HTML",
    )
    await call.answer()


@router.message(CustomReportFlow.dates)
async def custom_report_dates(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        return

    parts = (message.text or "").strip().split()
    if len(parts) != 2:
        await message.answer(
            "Send two dates, for example:\n<code>2026-07-01 2026-07-16</code>",
            parse_mode="HTML",
        )
        return

    try:
        start_date = datetime.strptime(parts[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        final_day = datetime.strptime(parts[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        await message.answer("Invalid date format. Use YYYY-MM-DD.")
        return

    if final_day < start_date:
        await message.answer("The end date must be on or after the start date.")
        return

    end_exclusive = final_day + timedelta(days=1)
    label = f"{parts[0]} to {parts[1]}"
    await message.answer(
        await build_sales_report(start_date, end_exclusive, label),
        reply_markup=report_menu(),
        parse_mode="HTML",
    )
    await state.clear()
