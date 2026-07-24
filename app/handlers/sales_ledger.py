from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select

from app.db.models import Order, Product, StockItem, User
from app.db.session import SessionLocal
from app.utils.security import is_admin

router = Router()


class SoldDataFlow(StatesGroup):
    custom_dates = State()
    user_lookup = State()


def menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Today", callback_data="sold:today"),
                InlineKeyboardButton(text="🕘 Yesterday", callback_data="sold:yesterday"),
            ],
            [
                InlineKeyboardButton(text="📆 7 Days", callback_data="sold:7d"),
                InlineKeyboardButton(text="🗓 30 Days", callback_data="sold:30d"),
            ],
            [
                InlineKeyboardButton(text="📊 1 Year", callback_data="sold:365d"),
                InlineKeyboardButton(text="✏️ Custom Dates", callback_data="sold:custom"),
            ],
            [
                InlineKeyboardButton(text="👤 Search User", callback_data="sold:user"),
                InlineKeyboardButton(text="📦 Recent 100", callback_data="sold:recent"),
            ],
            [InlineKeyboardButton(text="✖ Close", callback_data="sold:close")],
        ]
    )


def start_of_today() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def period(key: str) -> tuple[datetime | None, datetime | None, str]:
    now = datetime.now(timezone.utc)
    today = start_of_today()
    if key == "today":
        return today, now, "Today"
    if key == "yesterday":
        return today - timedelta(days=1), today, "Yesterday"
    if key == "7d":
        return today - timedelta(days=6), now, "Last 7 Days"
    if key == "30d":
        return today - timedelta(days=29), now, "Last 30 Days"
    if key == "365d":
        return today - timedelta(days=364), now, "Last 1 Year"
    if key == "recent":
        return None, None, "Recent 100 Sold Items"
    raise ValueError("Invalid period")


async def fetch_rows(
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    user_id: int | None = None,
    username: str | None = None,
    limit: int | None = None,
) -> list[dict]:
    async with SessionLocal() as session:
        stmt = (
            select(StockItem, Order, Product, User)
            .join(Order, StockItem.reserved_order_id == Order.id)
            .join(Product, Order.product_id == Product.id)
            .join(User, Order.user_id == User.id)
            .where(StockItem.status == "delivered")
        )

        if start is not None:
            stmt = stmt.where(StockItem.delivered_at >= start)
        if end is not None:
            stmt = stmt.where(StockItem.delivered_at < end)
        if user_id is not None:
            stmt = stmt.where(User.id == user_id)
        if username:
            stmt = stmt.where(User.username.ilike(username.lstrip("@")))

        stmt = stmt.order_by(StockItem.delivered_at.desc(), StockItem.id.desc())
        if limit:
            stmt = stmt.limit(limit)

        result = list((await session.execute(stmt)).all())

        rows: list[dict] = []
        order_ids_with_stock = set()
        for item, order, product, user in result:
            order_ids_with_stock.add(order.id)
            rows.append({
                "delivered_at": item.delivered_at or order.created_at,
                "order_id": order.id,
                "user_id": user.id,
                "first_name": user.first_name or "",
                "username": user.username or "",
                "product_id": product.id,
                "product": product.name,
                "order_quantity": order.quantity or 1,
                "item_id": item.id,
                "delivery_content": item.content,
                "payment_method": order.payment_method or "",
                "order_amount": float(order.amount or 0),
                "delivery_type": "stock",
            })

        # Manual-delivery orders do not necessarily have actual customer content in StockItem.
        manual_stmt = (
            select(Order, Product, User)
            .join(Product, Order.product_id == Product.id)
            .join(User, Order.user_id == User.id)
            .where(
                Order.delivered.is_(True),
                Product.delivery_mode == "manual",
            )
        )
        if start is not None:
            manual_stmt = manual_stmt.where(Order.created_at >= start)
        if end is not None:
            manual_stmt = manual_stmt.where(Order.created_at < end)
        if user_id is not None:
            manual_stmt = manual_stmt.where(User.id == user_id)
        if username:
            manual_stmt = manual_stmt.where(User.username.ilike(username.lstrip("@")))
        manual_stmt = manual_stmt.order_by(Order.id.desc())
        if limit:
            manual_stmt = manual_stmt.limit(limit)

        for order, product, user in (await session.execute(manual_stmt)).all():
            if order.id in order_ids_with_stock:
                continue
            rows.append({
                "delivered_at": order.created_at,
                "order_id": order.id,
                "user_id": user.id,
                "first_name": user.first_name or "",
                "username": user.username or "",
                "product_id": product.id,
                "product": product.name,
                "order_quantity": order.quantity or 1,
                "item_id": "",
                "delivery_content": order.delivery_record or "[manual delivery record unavailable for older order]",
                "payment_method": order.payment_method or "",
                "order_amount": float(order.amount or 0),
                "delivery_type": "manual",
            })

        rows.sort(
            key=lambda row: row["delivered_at"] or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        if limit:
            rows = rows[:limit]
        return rows


def display_name(row: dict) -> str:
    name = row["first_name"] or "Customer"
    if row["username"]:
        name += f" (@{row['username']})"
    return name


def format_time(value: datetime | None) -> str:
    if not value:
        return "Unknown"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def make_csv(rows: list[dict], filename: str) -> BufferedInputFile:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "delivered_at_utc",
        "order_id",
        "telegram_user_id",
        "customer_name",
        "telegram_username",
        "product_id",
        "product",
        "order_quantity",
        "stock_item_id",
        "exact_delivered_item",
        "payment_method",
        "order_amount_usd",
        "delivery_type",
    ])
    for row in rows:
        writer.writerow([
            format_time(row["delivered_at"]),
            row["order_id"],
            row["user_id"],
            row["first_name"],
            row["username"],
            row["product_id"],
            row["product"],
            row["order_quantity"],
            row["item_id"],
            row["delivery_content"],
            row["payment_method"],
            f"{row['order_amount']:.2f}",
            row["delivery_type"],
        ])
    return BufferedInputFile(output.getvalue().encode("utf-8-sig"), filename=filename)


async def send_ledger(target: Message, rows: list[dict], label: str) -> None:
    if not rows:
        await target.answer(f"🧾 No sold-item records found for <b>{escape(label)}</b>.", parse_mode="HTML")
        return

    unique_orders = len({r["order_id"] for r in rows})
    unique_users = len({r["user_id"] for r in rows})
    total_items = len(rows)

    preview = [
        f"🧾 <b>Sold Item Ledger — {escape(label)}</b>",
        "",
        f"📦 Sold items: <b>{total_items}</b>",
        f"🧾 Orders: <b>{unique_orders}</b>",
        f"👥 Customers: <b>{unique_users}</b>",
        "",
        "<b>Recent preview</b>",
    ]
    for row in rows[:10]:
        content = str(row["delivery_content"]).replace("\n", " ")
        if len(content) > 60:
            content = content[:57] + "..."
        preview.append(
            f"• #{row['order_id']} · {escape(row['product'])}\n"
            f"  👤 {escape(display_name(row))} · <code>{row['user_id']}</code>\n"
            f"  🎁 <code>{escape(content)}</code>\n"
            f"  🕒 {format_time(row['delivered_at'])}"
        )

    if len(rows) > 10:
        preview.append(f"\n…and {len(rows) - 10} more item(s) in the CSV.")

    await target.answer("\n".join(preview), parse_mode="HTML")

    safe_label = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)[:50]
    await target.answer_document(
        make_csv(rows, f"PrimeHub_Sold_Data_{safe_label}.csv"),
        caption=(
            f"📊 Sold data export: {label}\n"
            "Includes exact delivered item, order, customer, product, payment method and date."
        ),
    )


@router.message(Command("solddata", "salesledger"))
async def solddata_command(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(
        "🧾 <b>Prime Hub Sold Data</b>\n\n"
        "Choose how you want to view/export sold items:",
        reply_markup=menu(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("sold:"))
async def sold_callback(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return

    key = call.data.split(":", 1)[1]

    if key == "close":
        await call.message.edit_reply_markup(reply_markup=None)
        await call.answer()
        return

    if key == "custom":
        await state.set_state(SoldDataFlow.custom_dates)
        await call.message.answer(
            "✏️ Send dates like:\n<code>2026-07-01 2026-07-24</code>",
            parse_mode="HTML",
        )
        await call.answer()
        return

    if key == "user":
        await state.set_state(SoldDataFlow.user_lookup)
        await call.message.answer(
            "👤 Send the customer's Telegram ID or @username.\n"
            "Examples:\n<code>6606638945</code>\n<code>@customername</code>",
            parse_mode="HTML",
        )
        await call.answer()
        return

    start, end, label = period(key)
    rows = await fetch_rows(start=start, end=end, limit=100 if key == "recent" else None)
    await send_ledger(call.message, rows, label)
    await call.answer()


@router.message(SoldDataFlow.custom_dates)
async def sold_custom_dates(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").strip().split()
    if len(parts) != 2:
        await message.answer("Send two dates in YYYY-MM-DD format.")
        return
    try:
        start = datetime.strptime(parts[0], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        final = datetime.strptime(parts[1], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        await message.answer("Invalid date format. Use YYYY-MM-DD.")
        return
    if final < start:
        await message.answer("End date must be after or equal to start date.")
        return
    end = final + timedelta(days=1)
    rows = await fetch_rows(start=start, end=end)
    await send_ledger(message, rows, f"{parts[0]} to {parts[1]}")
    await state.clear()


@router.message(SoldDataFlow.user_lookup)
async def sold_user_lookup(message: Message, state: FSMContext):
    if not message.from_user or not is_admin(message.from_user.id):
        return

    value = (message.text or "").strip()
    if not value:
        await message.answer("Send a Telegram ID or @username.")
        return

    if value.isdigit():
        rows = await fetch_rows(user_id=int(value))
        label = f"User ID {value}"
    else:
        username = value.lstrip("@")
        rows = await fetch_rows(username=username)
        label = f"@{username}"

    await send_ledger(message, rows, label)
    await state.clear()
