import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import Order
from app.db.session import SessionLocal
from app.services.binance_pay import BinancePayClient, BinancePayAPIError
from app.services.delivery import deliver_order

logger = logging.getLogger(__name__)


def _pick(record: dict, *keys: str) -> Any:
    for key in keys:
        val = record.get(key)
        if val is not None and val != "":
            return val
    return None


def extract_binance_records(payload: dict) -> list[dict]:
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for key in ("data", "rows", "list", "transactions"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    return []


async def verify_binance_payment(
    session,
    order: Order,
    txid_hint: str | None = None,
) -> tuple[bool, str | None]:
    """Verify whether a Binance Pay transaction matches this order.

    Matches positive incoming USDT transfers with correct amount within the order's
    active timeframe that haven't been redeemed by any other order.
    """
    client = BinancePayClient()
    if not client.configured:
        logger.warning("BinancePayClient is not configured.")
        return False, None

    # Search window: 5 minutes before order creation until now
    order_created_ms = int(order.created_at.timestamp() * 1000) if order.created_at else int((datetime.now(timezone.utc) - timedelta(minutes=30)).timestamp() * 1000)
    start_time_ms = max(0, order_created_ms - (5 * 60 * 1000))
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    try:
        payload = await client.pay_transactions(
            start_time_ms=start_time_ms,
            end_time_ms=now_ms,
            limit=50,
        )
    except (BinancePayAPIError, Exception) as exc:
        logger.warning(f"Error querying Binance Pay transactions: {exc}")
        return False, None

    records = extract_binance_records(payload)
    target_amount = float(order.amount)

    for record in records:
        raw_amount = _pick(record, "amount", "totalFee")
        raw_currency = _pick(record, "currency", "asset")
        raw_txid = _pick(record, "transactionId", "orderId", "merchantTradeNo", "prepayId")

        if not raw_amount or not raw_txid:
            continue

        try:
            tx_amount = float(raw_amount)
        except (ValueError, TypeError):
            continue

        # Incoming payment must be positive
        if tx_amount <= 0:
            continue

        # Currency must match USDT (or order currency)
        currency_str = str(raw_currency or "").strip().upper()
        if currency_str and currency_str != "USDT":
            continue

        # Amount check (allow 0.005 tolerance for rounding)
        if abs(tx_amount - target_amount) > 0.005:
            # If user provided a specific txid_hint, check if the hint matches this record
            if txid_hint and str(raw_txid).strip().lower() == txid_hint.strip().lower():
                if abs(tx_amount - target_amount) > 0.05:
                    continue
            else:
                continue

        txid_str = str(raw_txid).strip()

        # If user gave a specific TxID hint, verify it matches
        if txid_hint and txid_str.lower() != txid_hint.strip().lower():
            continue

        # Check that this Binance transaction ID has not already been used
        provider_id = f"binance:{txid_str}"
        existing_stmt = select(Order.id).where(
            Order.provider_payment_id == provider_id,
            Order.id != order.id,
        )
        existing_used = (await session.execute(existing_stmt)).scalar_one_or_none()
        if existing_used:
            logger.info(f"Binance transaction {txid_str} was already credited to order #{existing_used}")
            continue

        # Valid matching transaction!
        order.status = "paid"
        order.provider_payment_id = provider_id
        order.expires_at = None
        await session.commit()
        return True, txid_str

    return False, None


async def monitor_loop(bot: Bot) -> None:
    """Background worker that continuously scans for incoming Binance Pay transfers."""
    client = BinancePayClient()
    if not client.configured:
        logger.info("Binance Pay monitor skipped: API keys not configured.")
        return

    logger.info("Binance Pay auto-verification monitor loop started.")

    while True:
        try:
            await asyncio.sleep(max(5, getattr(settings, "BINANCE_POLL_SECONDS", 15)))

            now = datetime.now(timezone.utc)
            async with SessionLocal() as session:
                stmt = (
                    select(Order)
                    .options(selectinload(Order.product))
                    .where(
                        Order.status == "waiting_binance",
                        Order.delivered.is_(False),
                        (Order.expires_at.is_(None) | (Order.expires_at > now)),
                    )
                )
                pending_orders = list((await session.execute(stmt)).scalars().all())

                if not pending_orders:
                    continue

                for order in pending_orders:
                    success, txid = await verify_binance_payment(session, order)
                    if success:
                        logger.info(f"Binance Pay order #{order.id} automatically verified (TxID: {txid}). Delivering...")
                        try:
                            # Update payment card in customer's chat
                            if order.payment_message_chat_id and order.payment_message_id:
                                try:
                                    await bot.edit_message_caption(
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

                            await deliver_order(bot, session, order)
                        except Exception as exc:
                            logger.error(f"Error delivering Binance Pay order #{order.id}: {exc}")

        except asyncio.CancelledError:
            logger.info("Binance Pay monitor loop stopped.")
            break
        except Exception as exc:
            logger.warning(f"Error in Binance Pay monitor loop: {exc}")
