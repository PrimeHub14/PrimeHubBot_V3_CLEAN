import logging
import re
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import quote_plus

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal
from app.keyboards import upi_waiting_kb, main_menu_kb
from app.utils.security import is_admin
from app.services.delivery import deliver_order
from app.services.loot_paglu import live_stock
from app.services.payment_messages import remove_previous_payment_message
from app.services.qr import make_address_qr

logger = logging.getLogger(__name__)

router = Router()


class UPIPayState(StatesGroup):
    waiting_utr = State()


def compute_upi_inr(amount_usd: float, order_id: int) -> float:
    """Add deterministic unique paise (0.01 to 0.89) based on order_id to prevent collision."""
    inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))
    base_inr = float(amount_usd) * inr_rate
    unique_paise = ((int(order_id) * 7 + 11) % 89) / 100.0
    return round(float(int(base_inr)) + unique_paise, 2)


@router.callback_query(F.data.startswith("directupi:"))
async def direct_upi(call: CallbackQuery):
    await call.answer()
    if not settings.UPI_ID:
        await call.message.answer("UPI payment is not configured yet. Please choose another payment method.")
        return

    parts = call.data.split(":")
    product_id = int(parts[1])
    quantity = max(1, int(parts[2]) if len(parts) > 2 else 1)

    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        product = await repo.get_product(session, product_id)
        local_stock = await repo.available_stock_count(session, product_id) if product else 0
        available_stock = await live_stock(product_id, local_stock) if product else 0
        if product and (not getattr(product, "stock_enabled", True) or getattr(product, "delivery_mode", "instant") == "manual"):
            available_stock = 999

        if not product or not product.active:
            await call.message.answer("Product not found or is currently unavailable.")
            return
        if available_stock <= 0:
            await call.message.answer("This product is out of stock.")
            return
        if quantity > available_stock:
            await call.message.answer(f"Only {available_stock} item(s) are available.")
            return

        try:
            order = await repo.create_order(
                session,
                call.from_user.id,
                product.id,
                product.price * quantity,
                "INR",
                "upi_auto",
                quantity,
            )
        except ValueError as exc:
            await call.message.answer(str(exc))
            return

        order.status = "waiting_upi"
        order.expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        await session.commit()

    inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))
    inr_amount = compute_upi_inr(float(order.amount), order.id)
    safe_name = escape(product.name or "")

    upi_deep_link = (
        f"upi://pay?pa={settings.UPI_ID}"
        f"&pn={quote_plus(settings.UPI_NAME)}"
        f"&am={inr_amount:.2f}&cu=INR"
        f"&tn=Order_{order.id}"
    )

    caption = (
        "🇮🇳 <b>UPI Payment — Instant Auto Delivery</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 Order ID: <code>#{order.id}</code>\n"
        f"📦 Product: <b>{safe_name}</b>\n"
        f"🔢 Quantity: <b>{quantity}</b>\n"
        f"💵 Total: <b>${float(order.amount):.2f} USD</b>\n"
        f"🇮🇳 Pay in INR: <b>₹{inr_amount:,.2f}</b> <i>(@ ₹{inr_rate:.1f}/$)</i>\n\n"
        f"UPI ID:\n<code>{settings.UPI_ID}</code>\n"
        f"Payee Name: <b>{escape(settings.UPI_NAME)}</b>\n\n"
        "⏳ Payment window: <b>15 minutes</b>\n\n"
        "🔍 <b>How to Pay & Receive Instantly:</b>\n"
        "1. Scan the QR code above with <b>PhonePe, GPay, or Paytm</b>.\n"
        f"2. Pay exactly <b>₹{inr_amount:.2f}</b> (paise included for instant match).\n"
        "3. Tap <b>'✍️ Submit 12-Digit UTR'</b> below and enter your 12-digit UPI reference number.\n\n"
        "⚡ <i>Your payment is verified against PhonePe and your product is delivered in seconds!</i>"
    )

    await remove_previous_payment_message(call.bot, order)

    # Clean up previous payment method menu so only the QR card is shown
    try:
        await call.message.delete()
    except Exception:
        pass

    kb = upi_waiting_kb(order.id)
    sent = None
    try:
        qr_file = make_address_qr(upi_deep_link)
        sent = await call.message.answer_photo(
            qr_file,
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception as exc:
        logger.warning(f"Failed to send UPI QR ({exc}), falling back to text.")
        sent = await call.message.answer(
            caption,
            parse_mode="HTML",
            reply_markup=kb,
        )

    if sent:
        async with SessionLocal() as session:
            await repo.set_order_payment_message(
                session,
                order.id,
                sent.chat.id,
                sent.message_id,
                caption,
            )


@router.callback_query(F.data.startswith("submitutr:"))
async def upi_ask_utr(call: CallbackQuery, state: FSMContext):
    await call.answer()
    order_id = int(call.data.split(":")[1])
    await state.clear()
    await state.update_data(upi_order_id=order_id)
    await state.set_state(UPIPayState.waiting_utr)

    await call.message.answer(
        "✍️ <b>Submit 12-Digit UPI Ref / UTR</b>\n\n"
        f"Order ID: <code>#{order_id}</code>\n\n"
        "Please send your <b>12-digit UTR / UPI Reference number</b> (e.g. <code>424512345678</code>) "
        "shown on your PhonePe, Google Pay, or Paytm receipt below:",
        parse_mode="HTML",
    )


@router.message(UPIPayState.waiting_utr)
async def upi_receive_utr(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    digits = "".join(re.findall(r"\d+", raw))

    if len(digits) < 10:
        await message.answer("Please send a valid 12-digit UPI reference number / UTR.")
        return

    utr = digits[:12] if len(digits) >= 12 else digits

    data = await state.get_data()
    order_id = data.get("upi_order_id")
    if not order_id:
        await state.clear()
        await message.answer("Session expired. Please select your order again from /orders.", reply_markup=main_menu_kb())
        return

    inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))

    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, int(order_id))
        if not order:
            await state.clear()
            await message.answer("Order not found.", reply_markup=main_menu_kb())
            return

        if order.delivered or order.status in {"delivered", "finished", "paid"}:
            await state.clear()
            await message.answer("✅ This order has already been verified and delivered!", reply_markup=main_menu_kb())
            return

        expected_inr = compute_upi_inr(float(order.amount), order.id)
        match = await repo.find_matching_upi_payment(session, utr, expected_inr)

        # Fallback: Check if there is an unclaimed PhonePe payment matching this amount
        if not match:
            stmt = select(repo.IncomingUpiPayment).where(
                repo.IncomingUpiPayment.order_id.is_(None),
            ).order_by(repo.IncomingUpiPayment.id.desc()).limit(10)
            unclaimed = list((await session.execute(stmt)).scalars().all())
            for c in unclaimed:
                if abs(float(c.amount) - expected_inr) <= 2.0:
                    c.utr = utr
                    match = c
                    break

        if match:
            await repo.claim_upi_payment(session, match, order)
            await state.clear()
            await message.answer(f"✅ <b>UPI Payment Confirmed!</b>\n\nUTR: <code>{utr}</code>\nDelivering your product...", parse_mode="HTML")
            try:
                if order.payment_message_chat_id and order.payment_message_id:
                    try:
                        await message.bot.edit_message_caption(
                            chat_id=order.payment_message_chat_id,
                            message_id=order.payment_message_id,
                            caption=(
                                f"✅ <b>UPI Payment Confirmed!</b>\n\n"
                                f"🧾 Order ID: <code>#{order.id}</code>\n"
                                f"UTR: <code>{utr}</code>\n"
                                f"💵 Amount: <b>₹{float(match.amount):,.2f}</b>\n\n"
                                f"⚡ <i>Delivering your purchase below...</i>"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                await deliver_order(message.bot, session, order)
            except Exception as exc:
                logger.error(f"Error delivering UPI order #{order.id}: {exc}")
        else:
            # Save the submitted UTR on the order.
            # If the PhonePe notification arrives on the phone 5-15 seconds later,
            # the webhook will automatically detect this order and auto-deliver!
            order.payment_proof_value = utr
            await session.commit()
            await message.answer(
                f"⏳ <b>UTR Recorded:</b> <code>{utr}</code>\n\n"
                f"We are checking PhonePe for your payment of <b>₹{expected_inr:,.2f}</b>.\n\n"
                "• Notifications usually arrive within 5–15 seconds.\n"
                "• As soon as PhonePe notifies our system, your product will be delivered automatically here!\n"
                "• If it doesn't arrive shortly, tap <b>'Check Status'</b> on the payment card above.",
                parse_mode="HTML",
            )


@router.callback_query(F.data.startswith("checkupi:"))
async def upi_check(call: CallbackQuery):
    order_id = int(call.data.split(":")[1])

    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await call.answer("Order not found.", show_alert=True)
            return

        if order.delivered or order.status in {"delivered", "finished", "paid"}:
            await call.answer("✅ This order has already been verified and delivered!", show_alert=True)
            return

        expected_inr = compute_upi_inr(float(order.amount), order.id)

        # If user previously typed a UTR, re-check it
        if order.payment_proof_value:
            match = await repo.find_matching_upi_payment(session, order.payment_proof_value, expected_inr)
            if match:
                await repo.claim_upi_payment(session, match, order)
                await call.answer("✅ Payment verified! Delivering your product...", show_alert=True)
                try:
                    if order.payment_message_chat_id and order.payment_message_id:
                        try:
                            await call.bot.edit_message_caption(
                                chat_id=order.payment_message_chat_id,
                                message_id=order.payment_message_id,
                                caption=(
                                    f"✅ <b>UPI Payment Confirmed!</b>\n\n"
                                    f"🧾 Order ID: <code>#{order.id}</code>\n"
                                    f"UTR: <code>{order.payment_proof_value}</code>\n"
                                    f"💵 Amount: <b>₹{float(match.amount):,.2f}</b>\n\n"
                                    f"⚡ <i>Delivering your purchase below...</i>"
                                ),
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass
                    await deliver_order(call.bot, session, order)
                except Exception as exc:
                    logger.error(f"Error delivering UPI order #{order.id}: {exc}")
                return

        await call.answer(
            "⏳ Payment not confirmed yet.\n\n"
            "Please complete your payment and tap 'Submit 12-Digit UTR' to verify instantly.",
            show_alert=True,
        )


@router.callback_query(F.data.startswith("cancelupi:"))
async def upi_cancel(call: CallbackQuery, state: FSMContext):
    await call.answer()
    order_id = int(call.data.split(":")[1])
    await state.clear()

    async with SessionLocal() as session:
        order = await repo.cancel_order(session, order_id, user_id=call.from_user.id)

    if order and order.status == "cancelled":
        try:
            await call.message.delete()
        except Exception:
            try:
                await call.message.edit_text("❌ Order cancelled.", reply_markup=None)
            except Exception:
                pass
        await call.message.answer(f"Order #{order_id} cancelled. No inventory was deducted.", reply_markup=main_menu_kb())
    else:
        await call.message.answer("Order could not be cancelled or has already been finalized.", reply_markup=main_menu_kb())


@router.message(Command("upistatus"))
async def upi_status_command(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return

    async with SessionLocal() as session:
        records = await repo.list_recent_upi_payments(session, limit=10)

    if not records:
        await message.answer(
            "📊 <b>UPI Status:</b> No PhonePe notifications have been recorded yet in the database.\n\n"
            "<b>Troubleshooting Checklist:</b>\n"
            "1. Did you receive the PhonePe notification on your phone?\n"
            "2. In MacroDroid, tap <b>System Log</b> to see if the HTTP Request succeeded or failed.\n"
            "3. Verify the URL in MacroDroid ends with <code>/webhook/phonepe</code>.",
            parse_mode="HTML",
        )
        return

    lines = [f"📊 <b>Recent PhonePe Recorded Payments ({len(records)}):</b>\n"]
    for r in records:
        status_text = f"Claimed by Order #{r.order_id}" if r.order_id else "Unclaimed"
        lines.append(
            f"• UTR: <code>{r.utr}</code> | <b>₹{float(r.amount):.2f}</b> | {status_text}"
        )

    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("upiapprove"))
async def upi_approve_command(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return

    parts = (message.text or "").strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Usage: <code>/upiapprove &lt;order_id&gt;</code>", parse_mode="HTML")
        return

    order_id = int(parts[1])
    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await message.answer(f"Order #{order_id} not found.")
            return
        if order.delivered or order.status in {"delivered", "finished", "paid"}:
            await message.answer(f"Order #{order_id} is already delivered.")
            return

        order.status = "paid"
        order.provider_payment_id = f"admin_approved:{order.payment_proof_value or 'manual'}"
        order.expires_at = None
        await session.commit()
        await deliver_order(message.bot, session, order)

    await message.answer(f"✅ Order #{order_id} approved and delivered to the customer.")


@router.message(Command("upidebug"))
async def upi_debug_command(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return

    from app.webhook import RECENT_WEBHOOK_LOGS
    if not RECENT_WEBHOOK_LOGS:
        await message.answer("No webhook requests have reached the server yet.")
        return

    lines = ["🔍 <b>Recent Webhook Hits Received from Phone:</b>\n"]
    for entry in RECENT_WEBHOOK_LOGS[-5:]:
        lines.append(f"⏰ {entry['time']}\n<code>{escape(entry['raw'])}</code>\n")

    await message.answer("\n".join(lines), parse_mode="HTML")


