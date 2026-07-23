from datetime import datetime, timezone
from decimal import Decimal
from aiogram import F, Router
from aiogram.types import CallbackQuery
from app.config import settings
from app.db import repo
from app.db.session import SessionLocal
from app.services.qr import make_address_qr

router = Router()


def unique_amount(price: Decimal, order_id: int) -> Decimal:
    suffix = Decimal((order_id % 900) + 1) / Decimal(1_000_000)
    return (price + suffix).quantize(Decimal("0.000001"))


@router.callback_query(F.data.startswith("directtrc:"))
async def direct_trc(call: CallbackQuery):
    if not settings.TRC20_RECEIVE_ADDRESS:
        await call.answer("TRC20 address is not configured.", show_alert=True)
        return
    product_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        product = await repo.get_product(session, product_id)
        if not product or not product.active:
            await call.answer("Product not found.", show_alert=True)
            return
        order = await repo.create_order(session, call.from_user.id, product, settings.CURRENCY, "usdttrc20_direct")
        expected = unique_amount(Decimal(str(product.price)), order.id)
        order.provider_payment_id = f"trc_expected:{expected:.6f}"
        order.status = "waiting_trc20"
        await session.commit()

    caption = (
        f"🟢 <b>USDT TRC20 Payment</b>\n\n"
        f"🧾 Order ID: <code>{order.id}</code>\n"
        f"📦 Product: <b>{product.name}</b>\n\n"
        f"Send exactly:\n<code>{expected:.6f} USDT</code>\n\n"
        f"TRC20 Address:\n<code>{settings.TRC20_RECEIVE_ADDRESS}</code>\n\n"
        f"⏳ Valid for {settings.TRC20_PAYMENT_TIMEOUT_MINUTES} minutes.\n"
        f"✅ The bot checks the confirmed TRON transaction automatically.\n"
        f"📦 Product delivery happens automatically after verification.\n\n"
        f"⚠️ Send only USDT on TRC20 and use the exact amount."
    )
    await call.message.answer_photo(make_address_qr(settings.TRC20_RECEIVE_ADDRESS), caption=caption, parse_mode="HTML")
    await call.answer()
