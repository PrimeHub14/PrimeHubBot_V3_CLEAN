from urllib.parse import urlencode

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal
from app.keyboards import (
    admin_wallet_review_kb,
    wallet_amount_kb,
    wallet_home_kb,
    wallet_proof_kb,
    wallet_topup_methods_kb,
)
from app.services.delivery import deliver_order
from app.services.nowpayments import NowPayments
from app.services.wallet import credit_wallet, debit_wallet
from app.utils.qr import qr_file
from app.utils.security import is_admin

router = Router()


class WalletTopupState(StatesGroup):
    waiting_custom_amount = State()


@router.callback_query(F.data == "wallet:home")
async def wallet_home(call: CallbackQuery):
    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        balance = await repo.wallet_balance(session, call.from_user.id)
    await call.message.answer(
        f"💰 <b>Prime Hub Wallet</b>\n\nAvailable balance: <b>${balance:.2f}</b>\n\nWallet purchases are confirmed and delivered instantly.",
        reply_markup=wallet_home_kb(), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data == "wallet:add")
async def wallet_add(call: CallbackQuery):
    await call.message.answer("Choose the amount to add:", reply_markup=wallet_amount_kb())
    await call.answer()


@router.callback_query(F.data == "wamount:custom")
async def wallet_custom_amount_prompt(call: CallbackQuery, state: FSMContext):
    await state.set_state(WalletTopupState.waiting_custom_amount)
    await call.message.answer(
        "✏️ Enter the amount you want to add in USD.\n\n"
        "Example: <code>7.50</code>\n"
        "Minimum: <b>$1.00</b>",
        parse_mode="HTML",
    )
    await call.answer()


@router.message(WalletTopupState.waiting_custom_amount)
async def wallet_custom_amount_message(message: Message, state: FSMContext):
    raw = (message.text or "").strip().replace("$", "").replace(",", "")
    try:
        amount = round(float(raw), 2)
    except ValueError:
        await message.answer("Please enter a valid number, for example <code>7.50</code>.", parse_mode="HTML")
        return

    if amount < 1:
        await message.answer("The minimum wallet top-up is <b>$1.00</b>. Please enter a higher amount.", parse_mode="HTML")
        return
    if amount > 10000:
        await message.answer("The maximum single top-up is <b>$10,000.00</b>.", parse_mode="HTML")
        return

    await state.clear()
    await message.answer(
        f"Add <b>${amount:.2f}</b> to your wallet. Choose a payment method:",
        reply_markup=wallet_topup_methods_kb(amount),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("wamount:"))
async def wallet_amount(call: CallbackQuery):
    amount_raw = call.data.split(":", 1)[1]
    if amount_raw == "custom":
        return
    amount = float(amount_raw)
    await call.message.answer(
        f"Add <b>${amount:.2f}</b> to your wallet. Choose a payment method:",
        reply_markup=wallet_topup_methods_kb(amount), parse_mode="HTML"
    )
    await call.answer()


@router.callback_query(F.data.startswith("wtopup:"))
async def wallet_topup(call: CallbackQuery):
    _, amount_raw, method = call.data.split(":")
    amount = float(amount_raw)
    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        topup = await repo.create_wallet_topup(session, call.from_user.id, amount, method)

        if method in {"usdtbep20", "usdttrc20"}:
            try:
                payment = await NowPayments().create_payment(
                    order_id=f"wallet-{topup.id}", price_amount=amount,
                    price_currency=settings.CURRENCY, pay_currency=method,
                    description=f"Prime Hub wallet top-up #{topup.id}",
                )
                payment_id = str(payment.get("payment_id") or payment.get("id") or "")
                await repo.set_wallet_topup_invoice(session, topup.id, payment_id)
                pay_amount = payment.get("pay_amount")
                pay_address = payment.get("pay_address")
                pay_currency = str(payment.get("pay_currency") or method).upper()
                qr_data = str(pay_address)
                await call.message.answer_photo(
                    qr_file(qr_data, "wallet-topup-qr.png"),
                    caption=(f"💰 <b>Wallet Top-up</b>\n\nTop-up ID: <code>{topup.id}</code>\n"
                             f"Credit after confirmation: <b>${amount:.2f}</b>\n\n"
                             f"Send exactly: <code>{pay_amount} {pay_currency}</code>\n"
                             f"To: <code>{pay_address}</code>\n\nThe wallet will be credited automatically after confirmation."),
                    parse_mode="HTML"
                )
            except Exception as exc:
                topup.status = "failed"
                await session.commit()
                await call.message.answer(f"Payment could not be created.\n\n{exc}")
            await call.answer()
            return

        if method == "binance":
            if not settings.BINANCE_PAY_ID:
                await call.message.answer("Binance Pay is not configured.")
                await call.answer(); return
            text = (f"🟡 <b>Binance Wallet Top-up</b>\n\nTop-up ID: <code>{topup.id}</code>\n"
                    f"Pay: <b>${amount:.2f}</b>\nBinance Pay ID: <code>{settings.BINANCE_PAY_ID}</code>")
            qr_data = settings.BINANCE_PAY_ID
        else:
            if not settings.UPI_ID:
                await call.message.answer("UPI is not configured.")
                await call.answer(); return
            inr = amount * settings.UPI_INR_PER_USD
            qr_data = "upi://pay?" + urlencode({"pa": settings.UPI_ID, "pn": settings.UPI_NAME, "am": f"{inr:.2f}", "cu": "INR", "tn": f"Prime Hub wallet top-up {topup.id}"})
            text = (f"⚪ <b>UPI Wallet Top-up</b>\n\nTop-up ID: <code>{topup.id}</code>\n"
                    f"Pay: <b>₹{inr:.2f}</b>\nUPI ID: <code>{settings.UPI_ID}</code>")

        topup.status = "awaiting_proof"
        await session.commit()
        await call.message.answer_photo(qr_file(qr_data, "wallet-topup-qr.png"), caption=text, reply_markup=wallet_proof_kb(topup.id), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("wproof:"))
async def wallet_proof_prompt(call: CallbackQuery):
    await call.message.answer("Send the payment screenshot, receipt, transaction ID, or UTR now.")
    await call.answer()


@router.message(F.photo | F.document | F.text)
async def wallet_proof_message(message: Message):
    if not message.from_user:
        return
    async with SessionLocal() as session:
        topup = await repo.latest_wallet_topup_waiting_for_proof(session, message.from_user.id)
        if not topup:
            return
        if message.photo:
            proof_type, proof_value = "photo", message.photo[-1].file_id
        elif message.document:
            proof_type, proof_value = "document", message.document.file_id
        else:
            proof_type, proof_value = "text", message.text or ""
        await repo.save_wallet_topup_proof(session, topup, proof_type, proof_value)

    summary = (f"💰 <b>Wallet top-up proof</b>\n\nTop-up ID: <code>{topup.id}</code>\n"
               f"User: <code>{message.from_user.id}</code>\nAmount: <b>${float(topup.amount):.2f}</b>\nMethod: {topup.method}")
    for admin_id in settings.admin_ids_set:
        if proof_type == "photo":
            await message.bot.send_photo(admin_id, proof_value, caption=summary, reply_markup=admin_wallet_review_kb(topup.id), parse_mode="HTML")
        elif proof_type == "document":
            await message.bot.send_document(admin_id, proof_value, caption=summary, reply_markup=admin_wallet_review_kb(topup.id), parse_mode="HTML")
        else:
            await message.bot.send_message(admin_id, summary + f"\n\nProof: <code>{proof_value}</code>", reply_markup=admin_wallet_review_kb(topup.id), parse_mode="HTML")
    await message.answer("✅ Top-up proof received. Your wallet will be credited after verification.")


@router.callback_query(F.data.startswith("wapprove:"))
async def wallet_approve(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized", show_alert=True); return
    topup_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        topup = await repo.get_wallet_topup(session, topup_id)
        if not topup or topup.status != "proof_submitted":
            await call.answer("Top-up is not waiting for approval", show_alert=True); return
        credited = await repo.credit_wallet_topup(session, topup)
    if credited:
        await call.bot.send_message(topup.user_id, f"✅ Wallet credited with <b>${float(topup.amount):.2f}</b>.", parse_mode="HTML")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Wallet credited")


@router.callback_query(F.data.startswith("wreject:"))
async def wallet_reject(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized", show_alert=True); return
    topup_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        topup = await repo.get_wallet_topup(session, topup_id)
        if not topup:
            await call.answer("Not found", show_alert=True); return
        topup.status = "rejected"
        await session.commit()
    await call.bot.send_message(topup.user_id, f"❌ Wallet top-up #{topup.id} was rejected. Contact support if needed.")
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Rejected")


@router.callback_query(F.data.startswith("walletpay:"))
async def wallet_pay(call: CallbackQuery):
    _, product_id_raw, quantity_raw = call.data.split(":")
    product_id, quantity = int(product_id_raw), max(1, min(int(quantity_raw), 13))
    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        product = await repo.get_product(session, product_id)
        if not product or not product.active:
            await call.answer("Product not found", show_alert=True); return
        total = float(product.price) * quantity
        balance = await repo.wallet_balance(session, call.from_user.id)
        if balance < total:
            await call.message.answer(f"Insufficient wallet balance.\nBalance: ${balance:.2f}\nRequired: ${total:.2f}", reply_markup=wallet_home_kb())
            await call.answer(); return
        try:
            order = await repo.create_order(session, call.from_user.id, product, settings.CURRENCY, "internal_wallet", quantity)
        except ValueError as exc:
            await call.answer(str(exc), show_alert=True); return
        if not await debit_wallet(session, call.from_user.id, total):
            await call.answer("Insufficient wallet balance", show_alert=True); return
        order.status = "paid"
        await session.commit()
        try:
            order = await repo.get_order_with_product(session, order.id)
            await deliver_order(call.bot, session, order)
        except Exception:
            await credit_wallet(session, call.from_user.id, total)
            order.status = "delivery_failed_refunded"
            await session.commit()
            raise
        new_balance = await repo.wallet_balance(session, call.from_user.id)
    await call.message.answer(f"✅ Paid from Prime Hub Wallet.\nRemaining balance: <b>${new_balance:.2f}</b>", parse_mode="HTML")
    await call.answer("Payment successful")
