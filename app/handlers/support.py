from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal
from app.utils.security import is_admin

router = Router()

ISSUES = {
    "payment": "Payment / Wallet Top-up",
    "delivery": "Product Not Received",
    "login": "Login / Redemption Problem",
    "replacement": "Replacement / Warranty",
    "other": "Other Issue",
}


class TicketFlow(StatesGroup):
    order_id = State()
    details = State()


def help_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💳 Payment / Wallet", callback_data="ticket:payment")],
        [InlineKeyboardButton(text="📦 Product Not Received", callback_data="ticket:delivery")],
        [InlineKeyboardButton(text="🔐 Login / Redemption", callback_data="ticket:login")],
        [InlineKeyboardButton(text="🛡 Replacement / Warranty", callback_data="ticket:replacement")],
        [InlineKeyboardButton(text="📝 Other Issue", callback_data="ticket:other")],
        [InlineKeyboardButton(text="🤖 Ask AI Assistant", callback_data="assistant:start")],
        [InlineKeyboardButton(text="🏠 Home", callback_data="home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("help"))
async def help_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🛟 <b>Prime Hub Help</b>\n\nChoose your issue:",
        reply_markup=help_keyboard(),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("ticket:"))
async def ticket_start(call: CallbackQuery, state: FSMContext):
    issue_key = call.data.split(":", 1)[1]
    if issue_key not in ISSUES:
        await call.answer("Invalid issue.", show_alert=True)
        return
    await state.clear()
    await state.update_data(issue_key=issue_key)
    await state.set_state(TicketFlow.order_id)
    await call.message.answer(
        f"🎫 <b>{ISSUES[issue_key]}</b>\n\n"
        "Send the order ID, or type <code>skip</code> if there is no order.",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(TicketFlow.order_id)
async def ticket_order(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if value.lower() == "skip":
        order_id = None
    elif value.lstrip("#").isdigit():
        order_id = int(value.lstrip("#"))
        async with SessionLocal() as session:
            order = await repo.get_order_with_product(session, order_id)
        if not order or order.user_id != message.from_user.id:
            await message.answer("That order was not found in your account. Send another order ID or type skip.")
            return
    else:
        await message.answer("Send a numeric order ID, for example 51, or type skip.")
        return
    await state.update_data(order_id=order_id)
    await state.set_state(TicketFlow.details)
    await message.answer(
        "Describe the issue clearly. You may send text, a screenshot, or a document. "
        "Do not send passwords, OTPs, private keys, seed phrases, or full payment credentials."
    )


@router.message(TicketFlow.details)
async def ticket_details(message: Message, state: FSMContext):
    data = await state.get_data()
    issue_key = data["issue_key"]
    order_id = data.get("order_id")
    attachment = None
    details = message.text or message.caption or "Attachment submitted"
    if message.photo:
        attachment = message.photo[-1].file_id
    elif message.document:
        attachment = message.document.file_id

    async with SessionLocal() as session:
        ticket = await repo.create_support_ticket(
            session,
            user_id=message.from_user.id,
            issue_type=ISSUES[issue_key],
            message=details,
            order_id=order_id,
            attachment_file_id=attachment,
        )

    await state.clear()
    await message.answer(
        f"✅ Support ticket <b>#{ticket.id}</b> created.\n"
        "Our team will reply in this chat.",
        parse_mode="HTML",
    )

    admin_text = (
        f"🎫 <b>New Support Ticket #{ticket.id}</b>\n\n"
        f"Type: <b>{ticket.issue_type}</b>\n"
        f"Customer: <code>{ticket.user_id}</code>\n"
        f"Order: <b>{ticket.order_id or 'None'}</b>\n\n"
        f"{ticket.message}\n\n"
        f"Reply: <code>/replyticket {ticket.id} your message</code>"
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Close Ticket", callback_data=f"closeticket:{ticket.id}")]
        ]
    )
    for admin_id in settings.admin_ids_set:
        try:
            if message.photo:
                await message.bot.send_photo(admin_id, attachment, caption=admin_text, parse_mode="HTML", reply_markup=markup)
            elif message.document:
                await message.bot.send_document(admin_id, attachment, caption=admin_text, parse_mode="HTML", reply_markup=markup)
            else:
                await message.bot.send_message(admin_id, admin_text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            pass


@router.message(Command("tickets"))
async def tickets_command(message: Message):
    async with SessionLocal() as session:
        tickets = await repo.user_support_tickets(session, message.from_user.id)
    if not tickets:
        await message.answer("You have no support tickets.")
        return
    lines = ["🎫 <b>My Support Tickets</b>"]
    for ticket in tickets:
        lines.append(f"#{ticket.id} | {ticket.issue_type} | {ticket.status}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("replyticket"))
async def reply_ticket(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer("Usage: /replyticket TICKET_ID your reply")
        return
    ticket_id = int(parts[1])
    reply = parts[2].strip()
    async with SessionLocal() as session:
        ticket = await repo.get_support_ticket(session, ticket_id)
        if not ticket:
            await message.answer("Ticket not found.")
            return
        await repo.reply_support_ticket(session, ticket, reply)
        user_id = ticket.user_id
    await message.bot.send_message(
        user_id,
        f"💬 <b>Reply to Ticket #{ticket_id}</b>\n\n{reply}",
        parse_mode="HTML",
    )
    await message.answer(f"✅ Reply sent for ticket #{ticket_id}.")


@router.callback_query(F.data.startswith("closeticket:"))
async def close_ticket_callback(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    ticket_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        ticket = await repo.get_support_ticket(session, ticket_id)
        if not ticket:
            await call.answer("Ticket not found.", show_alert=True)
            return
        await repo.close_support_ticket(session, ticket)
        user_id = ticket.user_id
    await call.bot.send_message(user_id, f"✅ Support ticket #{ticket_id} has been closed.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Ticket closed.")
