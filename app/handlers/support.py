from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

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
    details = State()
    admin_reply = State()


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Payment / Wallet", callback_data="ticket:payment")],
        [InlineKeyboardButton(text="📦 Product Not Received", callback_data="ticket:delivery")],
        [InlineKeyboardButton(text="🔐 Login / Redemption", callback_data="ticket:login")],
        [InlineKeyboardButton(text="🛡 Replacement / Warranty", callback_data="ticket:replacement")],
        [InlineKeyboardButton(text="📝 Other Issue", callback_data="ticket:other")],
        [InlineKeyboardButton(text="🤖 Ask AI Assistant", callback_data="assistant:start")],
        [InlineKeyboardButton(text="🏠 Home", callback_data="home")],
    ])


@router.message(Command("help"))
async def help_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🛟 <b>Prime Hub Help</b>\n\nChoose the issue you need help with:", reply_markup=help_keyboard(), parse_mode="HTML")


async def recent_orders_keyboard(user_id: int, issue_key: str) -> InlineKeyboardMarkup:
    async with SessionLocal() as session:
        orders = await repo.user_orders(session, user_id, limit=6)
        enriched = []
        for order in orders:
            full = await repo.get_order_with_product(session, order.id)
            enriched.append(full)
    rows = []
    for order in enriched:
        if not order:
            continue
        name = order.product.name[:25] if order.product else f"Product {order.product_id}"
        rows.append([InlineKeyboardButton(
            text=f"#{order.id} · {name} · {order.status}",
            callback_data=f"ticketorder:{issue_key}:{order.id}"
        )])
    rows.append([InlineKeyboardButton(text="📝 No order / General issue", callback_data=f"ticketorder:{issue_key}:none")])
    rows.append([InlineKeyboardButton(text="⬅️ Back", callback_data="help:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "help:home")
async def help_home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.answer("🛟 <b>Prime Hub Help</b>\n\nChoose your issue:", reply_markup=help_keyboard(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("paymenthelp:"))
async def payment_help(call: CallbackQuery, state: FSMContext):
    order_id = int(call.data.split(":")[1])
    await state.clear()
    await state.update_data(issue_key="payment", order_id=order_id)
    await state.set_state(TicketFlow.details)
    await call.message.answer(
        f"🛟 <b>Payment Help for Order #{order_id}</b>\n\n"
        "Describe what happened. You may send text, a screenshot, or a document.\n"
        "Do not send passwords, OTPs, private keys, seed phrases, or full card details.",
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("ticket:"))
async def ticket_start(call: CallbackQuery, state: FSMContext):
    issue_key = call.data.split(":", 1)[1]
    if issue_key not in ISSUES:
        await call.answer("Invalid issue.", show_alert=True)
        return
    await state.clear()
    await call.message.answer(
        f"🎫 <b>{ISSUES[issue_key]}</b>\n\nChoose the related recent order, or select general issue:",
        reply_markup=await recent_orders_keyboard(call.from_user.id, issue_key),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("ticketorder:"))
async def ticket_order_selected(call: CallbackQuery, state: FSMContext):
    _, issue_key, order_value = call.data.split(":", 2)
    order_id = None if order_value == "none" else int(order_value)
    await state.clear()
    await state.update_data(issue_key=issue_key, order_id=order_id)
    await state.set_state(TicketFlow.details)
    await call.message.answer(
        "Describe the issue clearly. You may send text, a screenshot, or a document.\n\n"
        "For payment problems, include the payment method and transaction/UTR ID when available.\n"
        "Never send passwords, OTPs, private keys, seed phrases, or full card details."
    )
    await call.answer()


@router.message(TicketFlow.details)
async def ticket_details(message: Message, state: FSMContext):
    data = await state.get_data()
    issue_key = data.get("issue_key", "other")
    order_id = data.get("order_id")
    attachment = None
    details = message.text or message.caption or "Attachment submitted"
    if message.photo:
        attachment = message.photo[-1].file_id
    elif message.document:
        attachment = message.document.file_id

    async with SessionLocal() as session:
        await repo.upsert_user(session, message.from_user)
        ticket = await repo.create_support_ticket(
            session, user_id=message.from_user.id, issue_type=ISSUES.get(issue_key, "Other Issue"),
            message=details, order_id=order_id, attachment_file_id=attachment,
        )
        order = await repo.get_order_with_product(session, order_id) if order_id else None

    await state.clear()
    await message.answer(
        f"✅ <b>Ticket #{ticket.id} received</b>\n\n"
        "Our team has been notified and will reply in this chat.\n"
        "You can continue using the store while we review your issue.",
        parse_mode="HTML",
    )

    full_name = " ".join(filter(None, [message.from_user.first_name, message.from_user.last_name])) or "Unknown"
    username = f"@{message.from_user.username}" if message.from_user.username else "Not set"
    order_lines = ""
    if order:
        product_name = order.product.name if order.product else f"Product {order.product_id}"
        order_lines = (
            f"\nOrder: <b>#{order.id}</b>\nProduct: <b>{escape(product_name)}</b>\n"
            f"Status: <b>{escape(order.status)}</b>\nPayment: <b>{escape(order.payment_method or 'Not selected')}</b>\n"
            f"Amount: <b>${float(order.amount):.2f}</b>\n"
        )

    admin_text = (
        f"🎫 <b>New Support Ticket #{ticket.id}</b>\n\n"
        f"Customer: <b>{escape(full_name)}</b>\nUsername: <b>{escape(username)}</b>\n"
        f"Telegram ID: <code>{message.from_user.id}</code>\n"
        f"Issue: <b>{escape(ticket.issue_type)}</b>{order_lines}\n"
        f"Message:\n{escape(ticket.message)}"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Reply", callback_data=f"ticketreply:{ticket.id}")],
        [InlineKeyboardButton(text="✅ Mark Resolved", callback_data=f"closeticket:{ticket.id}")],
    ])
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


@router.callback_query(F.data.startswith("ticketreply:"))
async def ticket_reply_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    ticket_id = int(call.data.split(":")[1])
    await state.set_state(TicketFlow.admin_reply)
    await state.update_data(reply_ticket_id=ticket_id)
    await call.message.answer(f"Send your reply for ticket #{ticket_id}.")
    await call.answer()


@router.message(TicketFlow.admin_reply)
async def ticket_reply_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    ticket_id = int(data["reply_ticket_id"])
    reply = (message.text or message.caption or "").strip()
    if not reply:
        await message.answer("Send a text reply.")
        return
    async with SessionLocal() as session:
        ticket = await repo.get_support_ticket(session, ticket_id)
        if not ticket:
            await message.answer("Ticket not found.")
            await state.clear()
            return
        await repo.reply_support_ticket(session, ticket, reply)
        user_id = ticket.user_id
    await message.bot.send_message(user_id, f"💬 <b>Reply to Ticket #{ticket_id}</b>\n\n{escape(reply)}", parse_mode="HTML")
    await message.answer(f"✅ Reply sent for ticket #{ticket_id}.")
    await state.clear()


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


@router.message(Command("ticketsadmin"))
async def tickets_admin(message: Message):
    if not is_admin(message.from_user.id):
        return
    async with SessionLocal() as session:
        from app.db.models import SupportTicket
        from sqlalchemy import select
        tickets = list((await session.execute(
            select(SupportTicket).where(SupportTicket.status != "closed").order_by(SupportTicket.id.desc()).limit(20)
        )).scalars().all())
    if not tickets:
        await message.answer("✅ No open support tickets.")
        return
    rows = [[InlineKeyboardButton(text=f"🎫 #{t.id} · {t.issue_type}", callback_data=f"ticketview:{t.id}")] for t in tickets]
    await message.answer("🎫 <b>Open Support Tickets</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")


@router.callback_query(F.data.startswith("ticketview:"))
async def ticket_view(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    ticket_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        ticket = await repo.get_support_ticket(session, ticket_id)
        user = await session.get(__import__("app.db.models", fromlist=["User"]).User, ticket.user_id) if ticket else None
        order = await repo.get_order_with_product(session, ticket.order_id) if ticket and ticket.order_id else None
    if not ticket:
        await call.answer("Ticket not found.", show_alert=True)
        return
    username = f"@{user.username}" if user and user.username else "Not set"
    name = user.first_name if user and user.first_name else "Unknown"
    text = f"🎫 <b>Ticket #{ticket.id}</b>\nCustomer: <b>{escape(name)}</b>\nUsername: <b>{escape(username)}</b>\nTelegram ID: <code>{ticket.user_id}</code>\n"
    if order:
        text += f"Order: <b>#{order.id}</b> · {escape(order.product.name if order.product else str(order.product_id))} · {escape(order.status)}\n"
    text += f"\nIssue: <b>{escape(ticket.issue_type)}</b>\n\n{escape(ticket.message)}"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Reply", callback_data=f"ticketreply:{ticket.id}")],
        [InlineKeyboardButton(text="✅ Mark Resolved", callback_data=f"closeticket:{ticket.id}")],
    ])
    await call.message.answer(text, reply_markup=markup, parse_mode="HTML")
    await call.answer()


@router.message(Command("replyticket"))
async def reply_ticket_legacy(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3 or not parts[1].isdigit():
        await message.answer("Usage: /replyticket TICKET_ID your reply")
        return
    ticket_id = int(parts[1]); reply = parts[2].strip()
    async with SessionLocal() as session:
        ticket = await repo.get_support_ticket(session, ticket_id)
        if not ticket:
            await message.answer("Ticket not found."); return
        await repo.reply_support_ticket(session, ticket, reply)
    await message.bot.send_message(ticket.user_id, f"💬 <b>Reply to Ticket #{ticket_id}</b>\n\n{escape(reply)}", parse_mode="HTML")
    await message.answer(f"✅ Reply sent for ticket #{ticket_id}.")


@router.callback_query(F.data.startswith("closeticket:"))
async def close_ticket_callback(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True); return
    ticket_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        ticket = await repo.get_support_ticket(session, ticket_id)
        if not ticket:
            await call.answer("Ticket not found.", show_alert=True); return
        await repo.close_support_ticket(session, ticket)
    await call.bot.send_message(ticket.user_id, f"✅ Support ticket #{ticket_id} has been marked resolved.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Ticket resolved.")
