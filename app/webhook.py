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


RECENT_WEBHOOK_LOGS = []


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
        raw_str = ""
        data = {}
        try:
            raw_bytes = await request.read()
            raw_str = raw_bytes.decode("utf-8", errors="replace").strip()
            if raw_str.startswith("{") and raw_str.endswith("}"):
                try:
                    import json
                    data = json.loads(raw_str)
                except Exception:
                    pass
        except Exception:
            pass

        # Record into recent debug logs
        import time
        RECENT_WEBHOOK_LOGS.append({
            "time": time.strftime("%H:%M:%S"),
            "raw": (raw_str or str(dict(request.query)))[:250],
        })
        if len(RECENT_WEBHOOK_LOGS) > 20:
            RECENT_WEBHOOK_LOGS.pop(0)

        # Also check query parameters in case GET was used
        query_text = " ".join(request.query.values()).strip()
        combined_text = " ".join([
            raw_str,
            query_text,
            str(data.get("title") or "") if isinstance(data, dict) else "",
            str(data.get("text") or "") if isinstance(data, dict) else "",
            str(data.get("message") or "") if isinstance(data, dict) else "",
            str(data.get("body") or "") if isinstance(data, dict) else "",
            str(data.get("notification") or "") if isinstance(data, dict) else "",
            str(data.get("content") or "") if isinstance(data, dict) else "",
        ]).strip()

        raw_utr = (
            str(data.get("utr") or data.get("ref") or data.get("txnId") or "").strip() if isinstance(data, dict) else ""
        ) or str(request.query.get("utr") or request.query.get("ref") or "").strip()
        raw_amount = (
            str(data.get("amount") or data.get("amt") or "").strip() if isinstance(data, dict) else ""
        ) or str(request.query.get("amount") or request.query.get("amt") or "").strip()

        # Regex extract 12-digit UTR anywhere in payload
        if not raw_utr and combined_text:
            utr_match = re.search(r'\b(\d{12})\b', combined_text)
            if utr_match:
                raw_utr = utr_match.group(1)

        # Regex extract INR amount anywhere in payload
        if not raw_amount and combined_text:
            amt_match = re.search(r'(?:₹|Rs\.?|INR)\s*([\d,]+(?:\.\d{1,2})?)', combined_text, re.IGNORECASE)
            if amt_match:
                raw_amount = amt_match.group(1).replace(",", "")
            else:
                amt_match2 = re.search(r'([\d,]+(?:\.\d{1,2})?)\s*(?:₹|Rs\.?|INR)', combined_text, re.IGNORECASE)
                if amt_match2:
                    raw_amount = amt_match2.group(1).replace(",", "")

        try:
            amount_val = float(raw_amount) if raw_amount else 0.0
        except ValueError:
            amount_val = 0.0

        if not raw_utr and amount_val <= 0:
            return web.json_response({
                "status": "online",
                "message": "PhonePe webhook received. No UTR or amount detected.",
                "snippet": (combined_text or raw_str)[:100]
            }, status=200)

        # If UTR was not in push notification, create a fallback reference
        if not raw_utr:
            raw_utr = f"PHONEPE_{int(time.time())}"

        sender = str(data.get("sender") or data.get("payer") or "").strip() or None

        async with SessionLocal() as session:
            record = await repo.record_incoming_upi(
                session,
                utr=raw_utr,
                amount=amount_val,
                sender=sender,
                raw_text=combined_text or str(data),
            )

            # Check if any open order with waiting_upi matches:
            # 1. By UTR
            # 2. Or by Amount!
            matched_order = None
            if raw_utr and not raw_utr.startswith("PHONEPE_"):
                stmt = select(Order).options(selectinload(Order.product)).where(
                    Order.status == "waiting_upi",
                    Order.payment_proof_value == raw_utr,
                    Order.delivered.is_(False),
                )
                matched_order = (await session.execute(stmt)).scalar_one_or_none()

            if not matched_order and amount_val > 0:
                from app.handlers.upi_pay import compute_upi_inr
                inr_rate = float(getattr(settings, "UPI_INR_PER_USD", 86.5))
                # Check recent open waiting_upi orders
                stmt = select(Order).options(selectinload(Order.product)).where(
                    Order.status == "waiting_upi",
                    Order.delivered.is_(False),
                ).order_by(Order.id.desc())
                pending_orders = list((await session.execute(stmt)).scalars().all())

                for p_order in pending_orders:
                    expected = compute_upi_inr(float(p_order.amount), p_order.id)
                    if abs(expected - amount_val) <= 0.05 or abs(round(float(p_order.amount) * inr_rate, 2) - amount_val) <= 0.5:
                        matched_order = p_order
                        break

            if matched_order:
                await repo.claim_upi_payment(session, record, matched_order)
                try:
                    if matched_order.payment_message_chat_id and matched_order.payment_message_id:
                        try:
                            await bot.edit_message_caption(
                                chat_id=matched_order.payment_message_chat_id,
                                message_id=matched_order.payment_message_id,
                                caption=(
                                    f"✅ <b>UPI Payment Confirmed!</b>\n\n"
                                    f"🧾 Order ID: <code>#{matched_order.id}</code>\n"
                                    f"UTR / Ref: <code>{raw_utr}</code>\n"
                                    f"💵 Amount: <b>₹{amount_val:,.2f}</b>\n\n"
                                    f"⚡ <i>Delivering your purchase below...</i>"
                                ),
                                parse_mode="HTML",
                            )
                        except Exception:
                            pass
                    await deliver_order(bot, session, matched_order)
                except Exception as exc:
                    pass

        return web.json_response({
            "status": "success",
            "utr": raw_utr,
            "amount": amount_val,
        })

    async def root_handler(request: web.Request) -> web.Response:
        if request.method == "POST":
            return await phonepe_webhook(request)
        return web.Response(text="PrimeHub Premium Store is running.")

    app.router.add_post("/nowpayments-webhook", nowpayments_webhook)
    app.router.add_get("/", root_handler)
    app.router.add_post("/", root_handler)

    # Register all path aliases so any URL works
    for path in (
        "/webhook/phonepe",
        "/webhook/upi",
        "/phonepe",
        "/phonepe-webhook",
        "/webhook",
        "/upi",
    ):
        app.router.add_get(path, phonepe_webhook)
        app.router.add_post(path, phonepe_webhook)

    return app
