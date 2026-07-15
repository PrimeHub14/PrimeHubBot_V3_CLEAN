from aiohttp import web
from aiogram import Bot
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.db.session import SessionLocal
from app.db.models import Order, WalletTopUp
from app.db import repo
from app.services.nowpayments import verify_ipn
from app.services.delivery import deliver_order

PAID_STATUSES = {"finished", "confirmed", "sending"}
FAILED_STATUSES = {"failed", "expired", "refunded"}


def create_app(bot: Bot) -> web.Application:
    app = web.Application()

    async def nowpayments_webhook(request: web.Request) -> web.Response:
        raw = await request.read()
        signature = request.headers.get("x-nowpayments-sig")
        if not verify_ipn(raw, signature):
            return web.Response(status=401, text="invalid signature")

        data = await request.json()
        payment_id = str(data.get("payment_id") or data.get("id") or "")
        status = str(data.get("payment_status") or "").lower()
        if not payment_id:
            return web.Response(text="missing payment id")

        async with SessionLocal() as session:
            stmt = select(Order).options(selectinload(Order.product)).where(Order.provider_payment_id == payment_id)
            order = (await session.execute(stmt)).scalar_one_or_none()
            if order:
                order.status = status
                await session.commit()
                if status in PAID_STATUSES and not order.delivered:
                    await deliver_order(bot, session, order)
                elif status in FAILED_STATUSES and not order.delivered:
                    await repo.release_stock_items(session, order.id)
                return web.Response(text="OK")

            topup = (await session.execute(select(WalletTopUp).where(WalletTopUp.provider_payment_id == payment_id))).scalar_one_or_none()
            if topup:
                topup.status = status
                await session.commit()
                if status in PAID_STATUSES and not topup.credited:
                    credited = await repo.credit_wallet_topup(session, topup)
                    if credited:
                        await bot.send_message(topup.user_id, f"✅ Wallet credited automatically with <b>${float(topup.amount):.2f}</b>.", parse_mode="HTML")
                return web.Response(text="OK")

        return web.Response(text="payment not found")

    app.router.add_post("/nowpayments-webhook", nowpayments_webhook)
    app.router.add_get("/", lambda request: web.Response(text="PrimeHub Premium Store is running."))
    return app
