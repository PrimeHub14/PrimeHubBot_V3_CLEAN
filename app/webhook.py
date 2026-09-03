import re
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

    async def phonepe_webhook(request: web.Request) -> web.Response:
        """Receive PhonePe Business notifications forwarded from mobile app."""
        try:
            data = {}
            if request.can_read_body:
                try:
                    data = await request.json()
                except Exception:
                    post_data = await request.post()
                    data = dict(post_data)
        except Exception:
            data = {}

        combined_text = " ".join([
            str(data.get("title") or ""),
            str(data.get("text") or ""),
            str(data.get("message") or ""),
            str(data.get("body") or ""),
            str(data.get("notification") or ""),
            str(data.get("content") or ""),
        ]).strip()

        raw_utr = str(data.get("utr") or data.get("ref") or data.get("txnId") or "").strip()
        raw_amount = str(data.get("amount") or data.get("amt") or "").strip()

        # Regex extract 12-digit UTR if not provided directly
        if not raw_utr and combined_text:
            utr_match = re.search(r'\b(\d{12})\b', combined_text)
            if utr_match:
                raw_utr = utr_match.group(1)

        # Regex extract INR amount
        if not raw_amount and combined_text:
            amt_match = re.search(r'(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)', combined_text, re.IGNORECASE)
            if amt_match:
                raw_amount = amt_match.group(1).replace(",", "")

        if not raw_utr:
            return web.json_response({"status": "ignored", "reason": "No 12-digit UTR found in notification"}, status=200)

        try:
            amount_val = float(raw_amount) if raw_amount else 0.0
        except ValueError:
            amount_val = 0.0

        sender = str(data.get("sender") or data.get("payer") or "").strip() or None

        async with SessionLocal() as session:
            record = await repo.record_incoming_upi(
                session,
                utr=raw_utr,
                amount=amount_val,
                sender=sender,
                raw_text=combined_text or str(data),
            )

            # Auto-deliver if an open waiting order already submitted this UTR
            stmt = select(Order).options(selectinload(Order.product)).where(
                Order.status == "waiting_upi",
                Order.payment_proof_value == raw_utr,
                Order.delivered.is_(False),
            )
            order = (await session.execute(stmt)).scalar_one_or_none()

            if order:
                await repo.claim_upi_payment(session, record, order)
                try:
                    if order.payment_message_chat_id and order.payment_message_id:
                        try:
                            await bot.edit_message_caption(
                                chat_id=order.payment_message_chat_id,
                                message_id=order.payment_message_id,
                                caption=(
                                    f"✅ <b>UPI Payment Confirmed!</b>\n\n"
                                    f"🧾 Order ID: <code>#{order.id}</code>\n"
                                    f"UTR: <code>{raw_utr}</code>\n"
                                    f"💵 Amount: <b>₹{amount_val:,.2f}</b>\n\n"
                                    f"⚡ <i>Delivering your purchase below...</i>"
                                ),
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass
                    await deliver_order(bot, session, order)
                except Exception as exc:
                    pass

        return web.json_response({
            "status": "success",
            "utr": raw_utr,
            "amount": amount_val,
        })

    app.router.add_post("/nowpayments-webhook", nowpayments_webhook)
    app.router.add_post("/webhook/phonepe", phonepe_webhook)
    app.router.add_post("/webhook/upi", phonepe_webhook)
    app.router.add_get("/", lambda request: web.Response(text="PrimeHub Premium Store is running."))
    return app
