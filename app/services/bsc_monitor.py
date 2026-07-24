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

# Binance-Peg BSC-USD (USDT) contract on BNB Smart Chain mainnet.
USDT_BEP20_CONTRACT = "0x55d398326f99059fF775485246999027B3197955"

# keccak256("Transfer(address,address,uint256)")
TRANSFER_TOPIC = (
    "0xddf252ad1be2c89b69c2b068fc378daa"
    "952ba7f163c4a11628f55a4df523b3ef"
)

USDT_DECIMALS = 18
_last_scanned_block: int | None = None


def expected_from_marker(marker: str | None) -> Decimal | None:
    if not marker or not marker.startswith("bep_expected:"):
        return None
    try:
        return Decimal(marker.split(":", 1)[1])
    except Exception:
        return None


def recipient_topic(address: str) -> str:
    clean = address.lower().removeprefix("0x")
    if len(clean) != 40:
        raise ValueError("Invalid BEP20 receiving address")
    return "0x" + ("0" * 24) + clean


def log_amount(log: dict) -> Decimal | None:
    try:
        return Decimal(int(log["data"], 16)) / (Decimal(10) ** USDT_DECIMALS)
    except Exception:
        return None


async def rpc(method: str, params: list) -> object:
    if not settings.BSC_RPC_URL:
        raise RuntimeError("BSC_RPC_URL is not configured")

    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    async with aiohttp.ClientSession() as client:
        async with client.post(
            settings.BSC_RPC_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        ) as response:
            body = await response.json(content_type=None)
            if response.status != 200:
                raise RuntimeError(f"BSC RPC HTTP {response.status}: {body}")
            if body.get("error"):
                raise RuntimeError(f"BSC RPC error: {body['error']}")
            return body.get("result")


async def latest_block_number() -> int:
    result = await rpc("eth_blockNumber", [])
    if not isinstance(result, str):
        raise RuntimeError("BSC RPC returned an invalid block number")
    return int(result, 16)


async def fetch_transfer_logs(from_block: int, to_block: int) -> list[dict]:
    if to_block < from_block:
        return []

    result = await rpc(
        "eth_getLogs",
        [{
            "fromBlock": hex(from_block),
            "toBlock": hex(to_block),
            "address": USDT_BEP20_CONTRACT,
            "topics": [
                TRANSFER_TOPIC,
                None,
                recipient_topic(settings.BEP20_RECEIVE_ADDRESS),
            ],
        }],
    )
    return result if isinstance(result, list) else []


async def pending_orders_exist(now: datetime) -> bool:
    cutoff = now - timedelta(minutes=settings.BEP20_PAYMENT_TIMEOUT_MINUTES)
    async with SessionLocal() as session:
        stmt = select(Order.id).where(
            Order.status == "waiting_bep20",
            Order.payment_method == "usdtbep20_direct",
            Order.created_at >= cutoff,
        ).limit(1)
        return (await session.execute(stmt)).scalar_one_or_none() is not None


async def verify_cycle(bot: Bot) -> None:
    global _last_scanned_block

    now = datetime.now(timezone.utc)
    if not await pending_orders_exist(now):
        await expire_old_orders(now)
        return

    latest = await latest_block_number()
    confirmed_to = latest - max(1, settings.BEP20_CONFIRMATIONS)
    if confirmed_to <= 0:
        return

    if _last_scanned_block is None or _last_scanned_block > confirmed_to:
        from_block = max(0, confirmed_to - max(100, settings.BEP20_BACKFILL_BLOCKS))
    else:
        from_block = _last_scanned_block + 1

    if from_block > confirmed_to:
        await expire_old_orders(now)
        return

    # NodeReal allows large eth_getLogs ranges, but chunking keeps each request modest.
    chunk_size = 2000
    cursor = from_block

    while cursor <= confirmed_to:
        chunk_end = min(cursor + chunk_size - 1, confirmed_to)
        logs = await fetch_transfer_logs(cursor, chunk_end)

        for log in logs:
            if log.get("removed") is True:
                continue

            txid = str(log.get("transactionHash") or "")
            if not txid:
                continue

            amount = log_amount(log)
            if amount is None:
                continue

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
                        Order.status == "waiting_bep20",
                        Order.payment_method == "usdtbep20_direct",
                    )
                    .order_by(Order.created_at.asc())
                )
                orders = list((await session.execute(stmt)).scalars().all())

                match = None
                for order in orders:
                    expected = expected_from_marker(order.provider_payment_id)
                    if expected == amount:
                        match = order
                        break

                if not match:
                    continue

                # Record txid BEFORE delivery so the same payment can never be reused.
                match.provider_payment_id = txid
                match.status = "confirmed"
                await session.commit()

                try:
                    await deliver_order(bot, session, match)
                    logger.info(
                        "Delivered BEP20 order %s with tx %s",
                        match.id,
                        txid,
                    )
                except Exception as exc:
                    match.status = "payment_confirmed_delivery_pending"
                    await session.commit()
                    logger.exception(
                        "BEP20 payment confirmed but delivery failed for order %s",
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
                                    "⚠️ BEP20 payment confirmed but delivery failed\n"
                                    f"Order #{match.id}\n"
                                    f"TXID: {txid}\n"
                                    f"Error: {exc}"
                                ),
                            )
                        except Exception:
                            pass

        _last_scanned_block = chunk_end
        cursor = chunk_end + 1

    await expire_old_orders(now)


async def expire_old_orders(now: datetime) -> None:
    cutoff = now - timedelta(minutes=settings.BEP20_PAYMENT_TIMEOUT_MINUTES)
    async with SessionLocal() as session:
        stmt = select(Order).where(
            Order.status == "waiting_bep20",
            Order.payment_method == "usdtbep20_direct",
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
            logger.exception("BEP20 monitor cycle failed")

        await asyncio.sleep(max(10, settings.BEP20_POLL_SECONDS))
