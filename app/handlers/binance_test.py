from datetime import datetime, timedelta, timezone
from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.services.binance_pay import BinancePayAPIError, BinancePayClient
from app.utils.security import is_admin

router = Router()


def _pick(record: dict, *keys):
    for key in keys:
        value = record.get(key)
        if value is not None and value != "":
            return value
    return None


def _format_record(record: dict, index: int) -> str:
    txid = _pick(
        record,
        "transactionId",
        "orderId",
        "merchantTradeNo",
        "prepayId",
    )
    amount = _pick(record, "amount", "totalFee")
    currency = _pick(record, "currency", "asset")
    status = _pick(record, "status", "transactionStatus")
    payer = _pick(
        record,
        "counterPartyInfo",
        "payerInfo",
        "buyerInfo",
    )
    ts = _pick(record, "transactionTime", "createTime", "time", "timestamp")

    parts = [f"<b>{index}.</b>"]
    if txid is not None:
        parts.append(f"ID: <code>{escape(str(txid))}</code>")
    if amount is not None:
        parts.append(
            f"Amount: <b>{escape(str(amount))} {escape(str(currency or ''))}</b>".strip()
        )
    if status is not None:
        parts.append(f"Status: <b>{escape(str(status))}</b>")
    if ts is not None:
        parts.append(f"Time: <code>{escape(str(ts))}</code>")
    if payer is not None:
        text = str(payer)
        if len(text) > 120:
            text = text[:117] + "..."
        parts.append(f"Counterparty: <code>{escape(text)}</code>")

    return "\n".join(parts)


@router.message(Command("binancetest"))
async def binance_test(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return

    client = BinancePayClient()
    if not client.configured:
        await message.answer(
            "❌ Binance API credentials are not configured in Railway."
        )
        return

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=7)

    await message.answer(
        "🔍 Testing your read-only Binance API against Binance Pay history...\n"
        "No trading, transfer, or withdrawal action is performed."
    )

    try:
        payload = await client.pay_transactions(
            start_time_ms=int(start.timestamp() * 1000),
            end_time_ms=int(now.timestamp() * 1000),
            limit=10,
        )
    except BinancePayAPIError as exc:
        await message.answer(
            "❌ <b>Binance Pay API test failed</b>\n\n"
            f"<code>{escape(str(exc))}</code>\n\n"
            "This does not change any funds. It only means this API key/account "
            "could not read the Pay history endpoint with the current permissions.",
            parse_mode="HTML",
        )
        return
    except Exception as exc:
        await message.answer(
            "❌ <b>Unexpected Binance test error</b>\n\n"
            f"<code>{escape(str(exc))}</code>",
            parse_mode="HTML",
        )
        return

    data = payload.get("data")
    records = []

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        for key in ("data", "rows", "list", "transactions"):
            value = data.get(key)
            if isinstance(value, list):
                records = value
                break

    if not records:
        await message.answer(
            "✅ <b>Binance accepted the API request.</b>\n\n"
            "The Pay history endpoint is accessible with this read-only key, "
            "but no Binance Pay transactions were returned for the last 7 days.\n\n"
            "Next test: make one small Binance Pay transfer to your Binance Pay ID, "
            "then run /binancetest again.",
            parse_mode="HTML",
        )
        return

    preview = [
        "✅ <b>Binance Pay API access works.</b>",
        "",
        f"Returned records: <b>{len(records)}</b>",
        "",
        "<b>Recent sanitized preview</b>",
    ]

    for index, record in enumerate(records[:5], start=1):
        if isinstance(record, dict):
            preview.append(_format_record(record, index))
            preview.append("")

    preview.append(
        "The API key/secret are never displayed by this command."
    )

    await message.answer("\n".join(preview), parse_mode="HTML")
