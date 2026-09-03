import logging
from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal
from app.keyboards import binance_waiting_kb, main_menu_kb
from app.services.binance_monitor import verify_binance_payment
from app.services.delivery import deliver_order
from app.services.loot_paglu import live_stock
from app.services.payment_messages import remove_previous_payment_message
from app.services.qr import make_address_qr

logger = logging.getLogger(__name__)

router = Router()


class BinancePayState(StatesGroup):
    waiting_txid = State()


@router.callback_query(F.data.startswith("directbinance:"))
async def direct_binance(call: CallbackQuery):
    await call.answer()
    if not settings.BINANCE_PAY_ID:
        await call.message.answer("Binance Pay ID is not configured yet. Please choose another payment method.")
        return

    parts = call.data.split(":")
    product_id = int(parts[1])
    quantity = max(1, int(parts[2]) if len(parts) > 2 else 1)

    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        product = await repo.get_product(session, product_id)
        local_stock = await repo.available_stock_count(session, product_id) if product else 0
        available_stock = await live_stock(product_id, local_stock) if product else 0

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
                product,
                settings.CURRENCY,
                "binance_auto",
                quantity,
            )
        except ValueError as exc:
            await call.message.answer(str(exc))
            return

        order.status = "waiting_binance"
        order.expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=getattr(settings, "BINANCE_PAYMENT_TIMEOUT_MINUTES", 30)
        )
        await session.commit()

    safe_name = escape(product.name or "")
    timeout_mins = getattr(settings, "BINANCE_PAYMENT_TIMEOUT_MINUTES", 30)
    caption = (
        "🟡 <b>Binance Pay — Automatic Verification</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🧾 Order ID: <code>#{order.id}</code>\n"
        f"📦 Product: <b>{safe_name}</b>\n"
        f"🔢 Quantity: <b>{quantity}</b>\n"
        f"💵 Total: <b>${float(order.amount):.2f} USDT</b>\n\n"
        f"Send exact amount to Binance Pay ID:\n"
        f"<code>{settings.BINANCE_PAY_ID}</code>\n\n"
        f"⏳ Payment window: <b>{timeout_mins} minutes</b>\n\n"
        "🔍 <b>How to Pay:</b>\n"
        "1. Open Binance App ➔ Pay ➔ <b>Send</b>\n"
        f"2. Paste Pay ID: <code>{settings.BINANCE_PAY_ID}</code>\n"
        f"3. Send exactly <b>${float(order.amount):.2f} USDT</b>\n\n"
        "⚡ <i>Payment is verified automatically in the background. Once detected, your product is delivered instantly!</i>"
    )

    await remove_previous_payment_message(call.bot, order)

    try:
        await call.message.delete()
    except Exception:
        pass

    kb = binance_waiting_kb(order.id)
    sent = None
    try:
        qr_file = make_address_qr(settings.BINANCE_PAY_ID)
        sent = await call.message.answer_photo(
            qr_file,
            caption=caption,
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception as exc:
        logger.warning(f"Failed to send Binance QR ({exc}), falling back to text.")
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


@router.callback_query(F.data.startswith("binancecheck:"))
async def binance_check(call: CallbackQuery):
    order_id = int(call.data.split(":")[1])

    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await call.answer("Order not found.", show_alert=True)
            return

        if order.delivered or order.status in {"delivered", "finished", "paid"}:
            await call.answer("✅ This order has already been paid and delivered!", show_alert=True)
            return

        if order.status != "waiting_binance":
            await call.answer(f"Order status is {order.status}.", show_alert=True)
            return

        success, txid = await verify_binance_payment(session, order)
        if success:
            await call.answer("✅ Payment verified! Delivering your product...", show_alert=True)
            try:
                if order.payment_message_chat_id and order.payment_message_id:
                    try:
                        await call.bot.edit_message_caption(
                            chat_id=order.payment_message_chat_id,
                            message_id=order.payment_message_id,
                            caption=(
                                f"✅ <b>Binance Pay Confirmed!</b>\n\n"
                                f"🧾 Order ID: <code>#{order.id}</code>\n"
                                f"TxID: <code>{txid}</code>\n"
                                f"💵 Amount: <b>${float(order.amount):.2f} USDT</b>\n\n"
                                f"⚡ <i>Delivering your purchase below...</i>"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                await deliver_order(call.bot, session, order)
            except Exception as exc:
                logger.error(f"Error delivering Binance Pay order #{order.id}: {exc}")
        else:
            await call.answer(
                "⏳ Payment not detected yet.\n\n"
                "Please make sure you sent the exact amount to the Binance Pay ID. "
                "Transactions usually take 10–30 seconds to appear.",
                show_alert=True,
            )


@router.callback_query(F.data.startswith("binancetxid:"))
async def binance_ask_txid(call: CallbackQuery, state: FSMContext):
    await call.answer()
    order_id = int(call.data.split(":")[1])
    await state.clear()
    await state.update_data(binance_order_id=order_id)
    await state.set_state(BinancePayState.waiting_txid)

    await call.message.answer(
        "✍️ <b>Submit Binance Pay Order ID / TxID</b>\n\n"
        f"Order: <code>#{order_id}</code>\n\n"
        "Please send the <b>Transaction ID</b> or <b>Order ID</b> (e.g. <code>P_A244Q4EEKUS71115</code>) "
        "shown on your Binance payment receipt below:",
        parse_mode="HTML",
    )


@router.message(BinancePayState.waiting_txid)
async def binance_receive_txid(message: Message, state: FSMContext):
    raw_txid = (message.text or "").strip()
    if not raw_txid or len(raw_txid) < 5:
        await message.answer("Please send a valid Binance Pay transaction ID or order ID.")
        return

    data = await state.get_data()
    order_id = data.get("binance_order_id")
    if not order_id:
        await state.clear()
        await message.answer("Session expired. Please select your order again from /orders.", reply_markup=main_menu_kb())
        return

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

        success, txid = await verify_binance_payment(session, order, txid_hint=raw_txid)
        if success:
            await state.clear()
            await message.answer(f"✅ <b>Payment Confirmed!</b>\n\nVerified TxID: <code>{txid}</code>\nDelivering your product...", parse_mode="HTML")
            try:
                if order.payment_message_chat_id and order.payment_message_id:
                    try:
                        await message.bot.edit_message_caption(
                            chat_id=order.payment_message_chat_id,
                            message_id=order.payment_message_id,
                            caption=(
                                f"✅ <b>Binance Pay Confirmed!</b>\n\n"
                                f"🧾 Order ID: <code>#{order.id}</code>\n"
                                f"TxID: <code>{txid}</code>\n"
                                f"💵 Amount: <b>${float(order.amount):.2f} USDT</b>\n\n"
                                f"⚡ <i>Delivering your purchase below...</i>"
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
                await deliver_order(message.bot, session, order)
            except Exception as exc:
                logger.error(f"Error delivering Binance Pay order #{order.id}: {exc}")
        else:
            await message.answer(
                f"❌ <b>Transaction not found or does not match!</b>\n\n"
                f"We could not find an incoming payment of <b>${float(order.amount):.2f} USDT</b> "
                f"matching TxID: <code>{escape(raw_txid)}</code>.\n\n"
                "• Check that you sent the exact amount.\n"
                "• Make sure it was sent to your store's Binance Pay ID.\n"
                "• Try tapping 'Check Payment Status' on the payment card above in a few seconds.",
                parse_mode="HTML",
            )


@router.callback_query(F.data.startswith("binancecancel:"))
async def binance_cancel(call: CallbackQuery, state: FSMContext):
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
