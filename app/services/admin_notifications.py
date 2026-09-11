import logging
from html import escape
from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import Order, User

logger = logging.getLogger(__name__)


async def notify_admins_new_sale(bot: Bot, session: AsyncSession, order: Order) -> None:
    """Send real-time celebratory notification to all admins when an order is completed/delivered."""
    try:
        user = await session.get(User, order.user_id)
        customer_name = " ".join(filter(None, [user.first_name, user.last_name])) if user else f"User {order.user_id}"
        username = f"@{user.username}" if user and user.username else "No username"
        product_name = order.product.name if order.product else f"Product #{order.product_id}"

        # INR estimate if UPI or general
        inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))
        inr_val = float(order.amount) * inr_rate

        pay_method = (order.payment_method or "Automated").upper()
        utr_info = f"\n🔢 UTR / Ref: <code>{escape(str(order.payment_proof_value))}</code>" if order.payment_proof_value else ""
        supplier_info = f"\n🌐 Supplier: <b>{escape(order.supplier_source)}</b> (Ref #{order.supplier_order_id})" if order.supplier_source else ""

        text = (
            "🎉 <b>New Sale Completed & Delivered!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 Order ID: <b>#{order.id}</b>\n"
            f"📦 Product: <b>{escape(product_name)}</b>\n"
            f"🔢 Quantity: <b>{order.quantity or 1}</b>\n"
            f"💵 Total: <b>${float(order.amount):.2f}</b> (approx ₹{inr_val:,.2f})\n"
            f"💳 Payment: <b>{escape(pay_method)}</b>{utr_info}{supplier_info}\n\n"
            f"👤 Customer: <b>{escape(customer_name)}</b>\n"
            f"📱 Handle: <b>{escape(username)}</b>\n"
            f"🆔 Telegram ID: <code>{order.user_id}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "✅ Product items delivered to customer."
        )

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🔍 View Order #{order.id}", callback_data=f"adminorder:{order.id}")],
        ])

        for admin_id in settings.admin_ids_set:
            try:
                await bot.send_message(admin_id, text, reply_markup=markup, parse_mode="HTML")
            except Exception as exc:
                logger.warning(f"Could not send sale notification to admin {admin_id}: {exc}")
    except Exception as exc:
        logger.error(f"Error in notify_admins_new_sale: {exc}")


async def notify_admins_upi_submitted(
    bot: Bot,
    session: AsyncSession,
    order: Order,
    utr: str,
    expected_inr: float,
    from_user,
) -> None:
    """Send high-priority alert to admins when a customer submits a UPI UTR that needs verification."""
    try:
        customer_name = " ".join(filter(None, [getattr(from_user, "first_name", ""), getattr(from_user, "last_name", "")])) or f"User {order.user_id}"
        username = f"@{from_user.username}" if getattr(from_user, "username", None) else "No username"
        product_name = order.product.name if order.product else f"Product #{order.product_id}"

        text = (
            "🔔 <b>UPI Payment / UTR Submitted</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "A customer has submitted a UPI transaction ID for verification:\n\n"
            f"🧾 Order ID: <b>#{order.id}</b>\n"
            f"📦 Product: <b>{escape(product_name)}</b>\n"
            f"🔢 Quantity: <b>{order.quantity or 1}</b>\n"
            f"💵 Expected: <b>₹{expected_inr:,.2f}</b> (${float(order.amount):.2f})\n"
            f"🔢 Submitted UTR: <code>{escape(utr)}</code>\n\n"
            f"👤 Customer: <b>{escape(customer_name)}</b>\n"
            f"📱 Handle: <b>{escape(username)}</b>\n"
            f"🆔 Telegram ID: <code>{order.user_id}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "<i>Verify ₹" + f"{expected_inr:,.2f}" + " in your PhonePe / UPI app and tap below to deliver instantly:</i>"
        )

        markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🚀 Approve & Deliver Order #{order.id}", callback_data=f"adminapprove:{order.id}")],
            [
                InlineKeyboardButton(text=f"🔍 View Order #{order.id}", callback_data=f"adminorder:{order.id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"adminreject:{order.id}"),
            ],
        ])

        for admin_id in settings.admin_ids_set:
            try:
                await bot.send_message(admin_id, text, reply_markup=markup, parse_mode="HTML")
            except Exception as exc:
                logger.warning(f"Could not send UTR alert to admin {admin_id}: {exc}")
    except Exception as exc:
        logger.error(f"Error in notify_admins_upi_submitted: {exc}")