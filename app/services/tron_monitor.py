import asyncio, logging
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
    url = f"https://api.trongrid.io/v1/accounts/{settings.TRC20_RECEIVE_ADDRESS}/transactions/trc20"
    params = {
        "only_confirmed": "true",
        "only_to": "true",
        "contract_address": USDT_TRC20_CONTRACT,
        "limit": "200",
        "order_by": "block_timestamp,desc",
        "min_timestamp": str(max(0, min_timestamp_ms)),
    }
    headers = {"TRON-PRO-API-KEY": settings.TRONGRID_API_KEY} if settings.TRONGRID_API_KEY else {}
    async with aiohttp.ClientSession() as client:
        async with client.get(url, params=params, headers=headers, timeout=30) as r:
            if r.status != 200:
                logger.warning("TronGrid %s: %s", r.status, (await r.text())[:300])
                return []
            return (await r.json(content_type=None)).get("data", [])


async def verify_cycle(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.TRC20_PAYMENT_TIMEOUT_MINUTES)
    async with SessionLocal() as session:
        stmt = select(Order).options(selectinload(Order.product)).where(
            Order.status == "waiting_trc20",
            Order.payment_method == "usdttrc20_direct",
            Order.created_at >= cutoff,
        ).order_by(Order.created_at.asc())
        pending = list((await session.execute(stmt)).scalars().all())
    if not pending:
        return

    min_ts = int((min(o.created_at for o in pending) - timedelta(minutes=1)).timestamp() * 1000)
    transfers = await fetch_transfers(min_ts)

    for tx in transfers:
        txid = str(tx.get("transaction_id") or "")
        if not txid or str(tx.get("to") or "") != settings.TRC20_RECEIVE_ADDRESS:
            continue
        token = str(tx.get("token_info", {}).get("address") or "")
        if token and token != USDT_TRC20_CONTRACT:
            continue
        amount = tx_amount(tx)
        if amount is None:
            continue
        tx_time_ms = int(tx.get("block_timestamp") or 0)

        async with SessionLocal() as session:
            already = (await session.execute(select(Order.id).where(Order.provider_payment_id == txid))).scalar_one_or_none()
            if already:
                continue
            stmt = select(Order).options(selectinload(Order.product)).where(
                Order.status == "waiting_trc20",
                Order.payment_method == "usdttrc20_direct",
            ).order_by(Order.created_at.asc())
            orders = list((await session.execute(stmt)).scalars().all())
            match = None
            for order in orders:
                expected = expected_from_marker(order.provider_payment_id)
                if expected == amount and (not tx_time_ms or int(order.created_at.timestamp()*1000) <= tx_time_ms):
                    match = order
                    break
            if not match:
                continue
            match.provider_payment_id = txid
            match.status = "confirmed"
            await session.commit()
            await deliver_order(bot, session, match)
            logger.info("Delivered TRC20 order %s tx=%s", match.id, txid)

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
