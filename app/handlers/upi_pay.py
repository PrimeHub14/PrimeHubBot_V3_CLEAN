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
from app.keyboards import upi_waiting_kb, upi_status_kb, main_menu_kb
from app.utils.security import is_admin
from app.services.delivery import deliver_order
from app.services.loot_paglu import live_stock
from app.services.payment_messages import remove_previous_payment_message
from app.services.qr import make_address_qr

logger = logging.getLogger(__name__)

router = Router()


class UPIPayState(StatesGroup):
    waiting_utr = State()


def compute_upi_inr(amount_usd: float, order_id: int = 0) -> int:
    """Return clean rounded integer INR amount (no decimals) as requested by user."""
    inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))
    return int(round(float(amount_usd) * inr_rate))


@router.callback_query(F.data.startswith("directupi:"))
async def direct_upi(call: CallbackQuery):
    await call.answer()
    from app.services.ekqr import ekqr_client
    if not settings.UPI_ID and not ekqr_client.is_configured():
        await call.message.answer("UPI payment is not configured yet. Please choose another payment method.")
        return

    parts = call.data.split(":")
    product_id = int(parts[1])
    quantity = max(1, int(parts[2]) if len(parts) > 2 else 1)

    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        product = await repo.get_product(session, product_id)
        if not product or not product.active:
            await call.message.answer("Product not found or is currently unavailable.")
            return

        from app.services.ventebot import get_effective_product_stock
        available_stock = await get_effective_product_stock(session, product)

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
                product,
                settings.CURRENCY,
                "upi_auto",
                quantity,
            )
        except Exception as exc:
            logger.exception(f"Failed to create UPI order: {exc}")
            await call.message.answer(f"⚠️ Could not create order: {exc}")
            return

        order.status = "waiting_upi"
        order.expires_at = datetime.now(timezone.utc) + timedelta(minutes=15)
        await session.commit()

    inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))
    inr_amount = compute_upi_inr(float(order.amount), order.id)
    safe_name = escape(product.name or "")
    payee_upi = settings.UPI_ID or "primehubus@axl"
    payee_name = settings.UPI_NAME or "Abdullah"

    # Try creating dynamic QR / order on EkQR
    ekqr_data = None
    pay_url = None
    upi_deep_link = None

    if ekqr_client.is_configured():
        cust_name = call.from_user.first_name if call.from_user else "Customer"
        ekqr_data = await ekqr_client.create_order(
            order_id=order.id,
            amount_inr=inr_amount,
            product_name=product.name,
            customer_name=cust_name,
        )
        if ekqr_data:
            pay_url = ekqr_data.get("payment_url")
            intent = ekqr_data.get("upi_intent") or {}
            upi_deep_link = intent.get("bhim_link")

    if not upi_deep_link:
        upi_deep_link = (
            f"upi://pay?pa={payee_upi}"
            f"&pn={quote_plus(payee_name)}"
            f"&am={inr_amount}&cu=INR"
            f"&tn=Order_{order.id}"
        )

    caption = (
        "🇮🇳 <b>UPI Payment — Instant Auto Delivery</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 Order ID: <code>#{order.id}</code>\n"
        f"📦 Product: <b>{safe_name}</b>\n"
        f"🔢 Quantity: <b>{quantity}</b>\n"
        f"💵 Total: <b>${float(order.amount):.2f} USD</b>\n"
        f"🇮🇳 Pay in INR: <b>₹{inr_amount:,}</b> <i>(@ ₹{inr_rate:.1f}/$)</i>\n\n"
        f"UPI ID:\n<code>{payee_upi}</code>\n"
        f"Payee Name: <b>{escape(payee_name)}</b>\n\n"
        "⏳ Payment window: <b>15 minutes</b>\n\n"
        "🔍 <b>How to Pay & Receive Instantly:</b>\n"
        "1. Tap <b>'📲 Tap to Pay'</b> below or scan the QR code with <b>PhonePe, GPay, or Paytm</b>.\n"
        f"2. Pay exactly <b>₹{inr_amount:,}</b>.\n"
        "3. Once paid, the bot auto-verifies your payment and delivers your product instantly!\n\n"
        "⚡ <i>Instant automated delivery — zero waiting time!</i>"
    )

    await remove_previous_payment_message(call.bot, order)

    chat_id = call.message.chat.id
    # Clean up previous payment method menu so only the QR card is shown
    try:
        await call.message.delete()
    except Exception:
        pass

    kb = upi_waiting_kb(order.id, pay_url=pay_url)
    sent = None
    try:
        qr_file = make_address_qr(upi_deep_link)
        sent = await call.bot.send_photo(
            chat_id=chat_id,
            photo=qr_file,
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception as exc:
        logger.warning(f"Failed to send UPI QR ({exc}), falling back to text.")
        sent = await call.bot.send_message(
            chat_id=chat_id,
            text=caption,
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


@router.callback_query(F.data.startswith("upipaid:"))
async def upi_paid_clicked(call: CallbackQuery):
    await call.answer()
    order_id = int(call.data.split(":")[1])

    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await call.message.answer("Order not found.")
            return

        if order.delivered or order.status in {"delivered", "completed", "paid"}:
            await call.answer("✅ This order has already been verified and delivered!", show_alert=True)
            return

        expected_inr = compute_upi_inr(float(order.amount), order.id)

        # 1. First, check with EkQR API directly if configured
        from app.services.ekqr import ekqr_client
        if ekqr_client.is_configured():
            status_data = await ekqr_client.check_order_status(order_id=order.id)
            if status_data and str(status_data.get("status", "")).lower() in {"success", "completed"}:
                utr = str(status_data.get("upi_txn_id") or f"EKQR_{order.id}")
                amt = float(status_data.get("amount") or expected_inr)
                record = await repo.record_incoming_upi(
                    session,
                    utr=utr,
                    amount=amt,
                    sender=str(status_data.get("customer_name") or "EkQR Customer"),
                    raw_text=str(status_data),
                )
                await repo.claim_upi_payment(session, record, order)
                await call.answer("✅ Payment confirmed! Delivering your purchase...", show_alert=True)
                if order.payment_message_chat_id and order.payment_message_id:
                    try:
                        await call.bot.edit_message_caption(
                            chat_id=order.payment_message_chat_id,
                            message_id=order.payment_message_id,
                            caption=(
                                f"✅ <b>UPI Payment Confirmed!</b>\n\n"
                                f"🧾 Order ID: <code>#{order.id}</code>\n"
                                f"UTR: <code>{utr}</code>\n"
                                f"💵 Amount: <b>₹{amt:,.2f}</b>\n\n"
                                f"⚡ <i>Delivering your purchase below...</i>"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                await deliver_order(call.bot, session, order)
                return

        # 2. Check local database for matched UTR
        if order.payment_proof_value:
            match = await repo.find_matching_upi_payment(session, order.payment_proof_value, expected_inr)
            if match:
                await repo.claim_upi_payment(session, match, order)
                await call.answer("✅ Payment verified! Delivering your product...", show_alert=True)
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
                return

        # 3. Not verified yet: Show the clean checking status view with Check Status and Submit UTR buttons!
        safe_prod = escape(order.product.name if order.product else f"Order #{order.id}")
        status_caption = (
            f"⏳ <b>Payment Verification in Progress</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 Order ID: <code>#{order.id}</code>\n"
            f"📦 Product: <b>{safe_prod}</b>\n"
            f"💵 Expected Amount: <b>₹{expected_inr:,}</b>\n\n"
            "• Bank verification is currently in progress.\n"
            "• If you just completed payment in your UPI app, please allow 5–10 seconds.\n"
            "• Your product will deliver automatically here the second the bank confirms!\n\n"
            "👉 Tap <b>'🔄 Check Status'</b> below to re-verify, or submit your 12-digit UTR:"
        )

        try:
            await call.message.edit_caption(
                caption=status_caption,
                reply_markup=upi_status_kb(order.id),
                parse_mode="HTML",
            )
        except Exception:
            try:
                await call.message.edit_text(
                    text=status_caption,
                    reply_markup=upi_status_kb(order.id),
                    parse_mode="HTML",
                )
            except Exception:
                pass


@router.callback_query(F.data.startswith("backtoupi:"))
async def upi_back_to_payment(call: CallbackQuery):
    await call.answer()
    order_id = int(call.data.split(":")[1])

    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await call.message.answer("Order not found.")
            return

        if order.delivered or order.status in {"delivered", "completed", "paid"}:
            await call.answer("✅ This order has already been verified and delivered!", show_alert=True)
            return

        inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))
        inr_amount = compute_upi_inr(float(order.amount), order.id)
        safe_name = escape(order.product.name if order.product else "")
        payee_upi = settings.UPI_ID or "primehubus@axl"
        payee_name = settings.UPI_NAME or "Abdullah"
        pay_url = order.invoice_url

        caption = (
            "🇮🇳 <b>UPI Payment — Instant Auto Delivery</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🧾 Order ID: <code>#{order.id}</code>\n"
            f"📦 Product: <b>{safe_name}</b>\n"
            f"🔢 Quantity: <b>{order.quantity or 1}</b>\n"
            f"💵 Total: <b>${float(order.amount):.2f} USD</b>\n"
            f"🇮🇳 Pay in INR: <b>₹{inr_amount:,}</b> <i>(@ ₹{inr_rate:.1f}/$)</i>\n\n"
            f"UPI ID:\n<code>{payee_upi}</code>\n"
            f"Payee Name: <b>{escape(payee_name)}</b>\n\n"
            "⏳ Payment window: <b>15 minutes</b>\n\n"
            "🔍 <b>How to Pay & Receive Instantly:</b>\n"
            "1. Tap <b>'📲 Tap to Pay'</b> below or scan the QR code with <b>PhonePe, GPay, or Paytm</b>.\n"
            f"2. Pay exactly <b>₹{inr_amount:,}</b>.\n"
            "3. Once paid, the bot auto-verifies your payment and delivers your product instantly!\n\n"
            "⚡ <i>Instant automated delivery — zero waiting time!</i>"
        )

        kb = upi_waiting_kb(order.id, pay_url=pay_url)

        try:
            await call.message.edit_caption(
                caption=caption,
                reply_markup=kb,
                parse_mode="HTML",
            )
        except Exception:
            try:
                await call.message.edit_text(
                    text=caption,
                    reply_markup=kb,
                    parse_mode="HTML",
                )
            except Exception:
                pass


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
            order.payment_proof_type = "upi_utr"
            order.status = "waiting_upi"
            await session.commit()

            from app.services.admin_notifications import notify_admins_upi_submitted
            try:
                await notify_admins_upi_submitted(message.bot, session, order, utr, expected_inr, message.from_user)
            except Exception:
                pass

            await message.answer(
                f"⏳ <b>UTR Recorded:</b> <code>{utr}</code>\n\n"
                f"We are checking PhonePe for your payment of <b>₹{expected_inr:,}</b>.\n\n"
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

        # 1. First check with EkQR API directly if configured
        from app.services.ekqr import ekqr_client
        if ekqr_client.is_configured():
            status_data = await ekqr_client.check_order_status(order_id=order.id)
            if status_data and str(status_data.get("status", "")).lower() in {"success", "completed"}:
                utr = str(status_data.get("upi_txn_id") or f"EKQR_{order.id}")
                amt = float(status_data.get("amount") or expected_inr)
                record = await repo.record_incoming_upi(
                    session,
                    utr=utr,
                    amount=amt,
                    sender=str(status_data.get("customer_name") or "EkQR Customer"),
                    raw_text=str(status_data),
                )
                await repo.claim_upi_payment(session, record, order)
                await call.answer("✅ Payment verified! Delivering your product...", show_alert=True)
                if order.payment_message_chat_id and order.payment_message_id:
                    try:
                        await call.bot.edit_message_caption(
                            chat_id=order.payment_message_chat_id,
                            message_id=order.payment_message_id,
                            caption=(
                                f"✅ <b>UPI Payment Confirmed!</b>\n\n"
                                f"🧾 Order ID: <code>#{order.id}</code>\n"
                                f"UTR: <code>{utr}</code>\n"
                                f"💵 Amount: <b>₹{amt:,.2f}</b>\n\n"
                                f"⚡ <i>Delivering your purchase below...</i>"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                await deliver_order(call.bot, session, order)
                return

        # 2. If user previously typed a UTR, re-check database records
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
            "⏳ Payment not detected yet.\n\n"
            "If you have already paid, please wait a few seconds and tap 'Check Status' again, or tap 'Submit 12-Digit UTR'.",
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


