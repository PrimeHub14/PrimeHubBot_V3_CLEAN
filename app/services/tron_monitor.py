import asyncio
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import aiohttp
from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.db.models import Order
from app.db.session import SessionLocal
from app.services.delivery import deliver_order

logger = logging.getLogger(__name__)

# Official USDT TRC20 contract on TRON mainnet.
USDT_TRC20_CONTRACT = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"


def expected_from_marker(marker: str | None) -> Decimal | None:
    if not marker or not marker.startswith("trc_expected:"):
        return None
    try:
        return Decimal(marker.split(":", 1)[1])
    except Exception:
        return None


def tx_amount(tx: dict) -> Decimal | None:
    try:
        raw = Decimal(str(tx["value"]))
        decimals = int(tx.get("token_info", {}).get("decimals", 6))
        return raw / (Decimal(10) ** decimals)
    except Exception:
        return None


async def fetch_transfers(min_timestamp_ms: int) -> list[dict]:
    if not settings.TRC20_RECEIVE_ADDRESS:
        return []

    url = (
        "https://api.trongrid.io/v1/accounts/"
        f"{settings.TRC20_RECEIVE_ADDRESS}/transactions/trc20"
    )
    params = {
        "only_confirmed": "true",
        "only_to": "true",
        "contract_address": USDT_TRC20_CONTRACT,
        "limit": "200",
        "order_by": "block_timestamp,desc",
        "min_timestamp": str(max(0, min_timestamp_ms)),
    }
    headers = (
        {"TRON-PRO-API-KEY": settings.TRONGRID_API_KEY}
        if settings.TRONGRID_API_KEY
        else {}
    )

    async with aiohttp.ClientSession() as client:
        async with client.get(url, params=params, headers=headers, timeout=30) as response:
            if response.status != 200:
                logger.warning(
                    "TronGrid returned %s: %s",
                    response.status,
                    (await response.text())[:500],
                )
                return []
            payload = await response.json(content_type=None)
            return payload.get("data", [])


async def verify_cycle(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.TRC20_PAYMENT_TIMEOUT_MINUTES)

    async with SessionLocal() as session:
        stmt = (
            select(Order)
            .options(selectinload(Order.product))
            .where(
                Order.status == "waiting_trc20",
                Order.payment_method == "usdttrc20_direct",
                Order.created_at >= cutoff,
            )
            .order_by(Order.created_at.asc())
        )
        pending = list((await session.execute(stmt)).scalars().all())

    if not pending:
        return

    earliest = min(order.created_at for order in pending)
    if earliest.tzinfo is None:
        earliest = earliest.replace(tzinfo=timezone.utc)
    min_ts = int((earliest - timedelta(minutes=1)).timestamp() * 1000)
    transfers = await fetch_transfers(min_ts)

    for tx in transfers:
        txid = str(tx.get("transaction_id") or tx.get("txID") or "")
        if not txid:
            continue

        if str(tx.get("to") or "") != settings.TRC20_RECEIVE_ADDRESS:
            continue

        token_address = str(tx.get("token_info", {}).get("address") or "")
        if token_address != USDT_TRC20_CONTRACT:
            continue

        amount = tx_amount(tx)
        if amount is None:
            continue

        tx_time_ms = int(tx.get("block_timestamp") or 0)

        async with SessionLocal() as session:
            # A blockchain transaction can unlock only one order.
            already_used = (
                await session.execute(
                    select(Order.id).where(Order.provider_payment_id == txid)
                )
            ).scalar_one_or_none()
            if already_used:
                continue

            stmt = (
                select(Order)
                .options(selectinload(Order.product))
                .where(
                    Order.status == "waiting_trc20",
                    Order.payment_method == "usdttrc20_direct",
                )
                .order_by(Order.created_at.asc())
            )
            orders = list((await session.execute(stmt)).scalars().all())

            match = None
            for order in orders:
                expected = expected_from_marker(order.provider_payment_id)
                if expected != amount:
                    continue

                created_at = order.created_at
                if created_at.tzinfo is None:
                    created_at = created_at.replace(tzinfo=timezone.utc)

                if tx_time_ms and int(created_at.timestamp() * 1000) > tx_time_ms:
                    continue

                match = order
                break

            if not match:
                continue

            # Save the immutable txid before delivery so it cannot be reused.
            match.provider_payment_id = txid
            match.status = "confirmed"
            await session.commit()

            try:
                await deliver_order(bot, session, match)
                logger.info("Delivered TRC20 order %s with tx %s", match.id, txid)
            except Exception as exc:
                # The payment is real even if delivery fails (for example stock ran out).
                # Keep the txid and surface the problem for manual resolution.
                match.status = "payment_confirmed_delivery_pending"
                await session.commit()
                logger.exception(
                    "TRC20 payment confirmed but delivery failed for order %s",
                    match.id,
                )
                try:
                    await bot.send_message(
                        match.user_id,
                        (
                            f"✅ Payment confirmed for order #{match.id}, but automatic "
                            "delivery needs support attention. Your payment is recorded."
                        ),
                    )
                except Exception:
                    pass
                for admin_id in settings.admin_ids_set:
                    try:
                        await bot.send_message(
                            admin_id,
                            (
                                "⚠️ TRC20 payment confirmed but delivery failed\n"
                                f"Order #{match.id}\n"
                                f"TXID: {txid}\n"
                                f"Error: {exc}"
                            ),
                        )
                    except Exception:
                        pass



async def expire_old_orders(now: datetime) -> None:
    cutoff = now - timedelta(minutes=settings.TRC20_PAYMENT_TIMEOUT_MINUTES)
    async with SessionLocal() as session:
        stmt = select(Order).where(
            Order.status == "waiting_trc20",
            Order.payment_method == "usdttrc20_direct",
            Order.created_at < cutoff,
        )
        expired = list((await session.execute(stmt)).scalars().all())
        for order in expired:
            order.status = "expired"
        if expired:
            await session.commit()


async def monitor_loop(bot: Bot) -> None:
    while True:
        try:
            await verify_cycle(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("TRC20 monitor cycle failed")

        await asyncio.sleep(max(10, settings.TRC20_POLL_SECONDS))
