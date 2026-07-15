from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal
from app.keyboards import categories_kb, main_menu_kb, wallet_home_kb

router = Router()


def _welcome_text(first_name: str | None = None) -> str:
    name = first_name or "friend"
    return (
        f"👋 Welcome, <b>{name}</b>!\n\n"
        f"🛍️ <b>{settings.STORE_NAME}</b>\n"
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


async def _show_home(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _register_user(message)
    text = _welcome_text(message.from_user.first_name if message.from_user else None)
    if settings.WELCOME_IMAGE_FILE_ID:
        await message.answer_photo(
            settings.WELCOME_IMAGE_FILE_ID,
            caption=text,
            reply_markup=main_menu_kb(),
            parse_mode="HTML",
        )
    else:
        await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")


@router.message(CommandStart())
async def start_command(message: Message, state: FSMContext) -> None:
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
    if not categories:
        await message.answer("No products are available yet.", reply_markup=main_menu_kb())
        return
    await message.answer(
        "📂 <b>Choose a category</b>",
        reply_markup=categories_kb(categories),
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


@router.message(Command("orders"))
async def orders_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await _register_user(message)
    async with SessionLocal() as session:
        orders = await repo.user_orders(session, message.from_user.id)
    if not orders:
        await message.answer(
            "📦 You have no orders yet. Start shopping and your orders will appear here.",
            reply_markup=main_menu_kb(),
        )
        return
    lines = ["📦 <b>My Recent Orders</b>"]
    for order in orders:
        lines.append(
            f"#{order.id} | Product {order.product_id} | Qty {order.quantity or 1} | "
            f"{order.status} | ${float(order.amount):.2f}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


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


