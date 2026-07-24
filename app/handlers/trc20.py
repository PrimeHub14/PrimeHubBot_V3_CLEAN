from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_DOWN

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal
from app.services.qr import make_address_qr
from app.keyboards import crypto_waiting_kb

router = Router()


def unique_amount(total: Decimal, order_id: int) -> Decimal:
    """Add a tiny unique suffix so concurrent payments to one address can be matched.

    The suffix is between 0.000001 and 0.009999 USDT.
    """
    suffix = Decimal((order_id % 9999) + 1) / Decimal(1_000_000)
    return (total + suffix).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)


@router.callback_query(F.data.startswith("directtrc:"))
async def direct_trc(call: CallbackQuery):
    if not settings.TRC20_RECEIVE_ADDRESS:
        await call.answer("TRC20 receiving address is not configured.", show_alert=True)
        return

    parts = call.data.split(":")
    product_id = int(parts[1])
    quantity = max(1, min(int(parts[2]) if len(parts) > 2 else 1, 13))

    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        product = await repo.get_product(session, product_id)
        available_stock = await repo.available_stock_count(session, product_id) if product else 0

        if not product or not product.active:
            await call.answer("Product not found.", show_alert=True)
            return
        if available_stock <= 0:
            await call.answer("This product is out of stock.", show_alert=True)
            return
        if quantity > available_stock:
            await call.answer(f"Only {available_stock} item(s) are available.", show_alert=True)
            return

        try:
            order = await repo.create_order(
                session,
                call.from_user.id,
                product,
                settings.CURRENCY,
                "usdttrc20_direct",
                quantity,
            )
        except ValueError as exc:
            await call.answer(str(exc), show_alert=True)
            return

        expected = unique_amount(Decimal(str(order.amount)), order.id)
        order.provider_payment_id = f"trc_expected:{expected:.6f}"
        order.status = "waiting_trc20"
        order.expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.TRC20_PAYMENT_TIMEOUT_MINUTES
        )
        await session.commit()

    caption = (
        "🟢 <b>USDT TRC20 — Automatic Verification</b>\n\n"
        f"🧾 Order ID: <code>{order.id}</code>\n"
        f"📦 Product: <b>{product.name}</b>\n"
        f"🔢 Quantity: <b>{quantity}</b>\n"
        f"💵 Store total: <b>${float(order.amount):.2f}</b>\n\n"
        "Send exactly:\n"
        f"<code>{expected:.6f} USDT</code>\n\n"
        "TRC20 address:\n"
        f"<code>{settings.TRC20_RECEIVE_ADDRESS}</code>\n\n"
        f"⏳ Payment window: <b>{settings.TRC20_PAYMENT_TIMEOUT_MINUTES} minutes</b>\n"
        "🔍 The bot checks confirmed USDT transfers on the TRON blockchain automatically.\n"
        "📦 After verification, delivery starts automatically.\n\n"
        "⚠️ Use <b>USDT TRC20 only</b> and send the <b>exact amount shown above</b>. "
        "The small decimal suffix identifies your order."
    )

    sent = await call.message.answer_photo(
        make_address_qr(settings.TRC20_RECEIVE_ADDRESS),
        caption=caption,
        parse_mode="HTML",
        reply_markup=crypto_waiting_kb(order.id),
    )

    # Lets the existing expiry UI know which payment message belongs to this order.
    async with SessionLocal() as session:
        await repo.set_order_payment_message(
            session,
            order.id,
            sent.chat.id,
            sent.message_id,
            caption,
        )

    await call.answer()
