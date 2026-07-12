from aiohttp import web
from aiogram import Bot
from sqlalchemy.orm import selectinload
from sqlalchemy import select
from app.db.session import SessionLocal
from app.db.models import Order
from app.services.nowpayments import verify_ipn
from app.services.delivery import deliver_order

PAID_STATUSES = {"finished", "confirmed", "sending"}


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

            if not order:
                return web.Response(text="order not found")

            order.status = status
            await session.commit()

            if status in PAID_STATUSES and not order.delivered:
                await deliver_order(bot, session, order)

        return web.Response(text="OK")

    app.router.add_post("/nowpayments-webhook", nowpayments_webhook)
    app.router.add_get("/", lambda request: web.Response(text="PrimeHub Premium Store V2 is running."))
    return app
