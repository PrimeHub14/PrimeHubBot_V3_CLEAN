from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta
from html import escape

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.db.session import SessionLocal
from app.db import repo

logger = logging.getLogger("meta_lead_recovery")


async def meta_lead_recovery_worker(bot: Bot) -> None:
    """
    Background worker that runs every 3 minutes to recover cold Meta ad leads.
    Step 0 -> 1: Follow-up at 1 hour after landing without order
    Step 1 -> 2: Follow-up at 24 hours with special prompt pack bonus
    """
    await asyncio.sleep(30)  # Initial grace period on bot boot
    logger.info("Meta Lead Recovery background worker started.")

    while True:
        try:
            now = datetime.now(timezone.utc)
            async with SessionLocal() as session:
                # 1. Look up active Gemini product ID for direct payment button
                gemini_products = await repo.search_products(session, "Gemini", limit=5)
                product = next(
                    (
                        p for p in gemini_products
                        if "gemini" in p.name.lower()
                        and ("18 month" in p.name.lower() or "18-month" in p.name.lower() or "18m" in p.name.lower())
                    ),
                    None,
                )
                if not product and gemini_products:
                    product = gemini_products[0]

                product_id = product.id if product else None
                product_price = float(product.price) if product else 0.0

                # 2. Check 1-hour abandoned leads (Step 0 -> Step 1)
                cutoff_1h = now - timedelta(hours=1)
                leads_1h = await repo.get_pending_meta_leads_for_followup(session, step=0, cutoff_time=cutoff_1h)

                for lead in leads_1h:
                    name = escape(lead.first_name or "there")
                    text = (
                        f"👋 <b>Hey {name}, noticed you checked out the Gemini AI Pro + 5TB 18-Month Plan!</b>\n\n"
                        "Did you run into any questions about single-click activation or need help with payment?\n\n"
                        "⚡ <b>Quick Highlights:</b>\n"
                        "• <b>Special Price: Just ₹199 Only!</b> (Regular <s>₹799</s>)\n"
                        "• <b>5TB Storage + Gemini Advanced</b> on your personal Google email\n"
                        "• <b>1-Month Replacement Warranty</b> included\n"
                        "• Accepted: UPI (PhonePe, GPay, Paytm), Binance Pay, USDT & Wallet\n\n"
                        "<i>Your reserved ₹199 redeem slot is held for you below:</i>"
                    )

                    buttons = []
                    if product_id:
                        buttons.append([InlineKeyboardButton(text=f"⚡ Activate Plan for ₹199 (${product_price:.2f})", callback_data=f"paymenu:{product_id}:1")])
                    buttons.append([
                        InlineKeyboardButton(text="💬 Talk to Support", callback_data="help:home"),
                        InlineKeyboardButton(text="🛍 View All Plans", callback_data="shop"),
                    ])
                    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

                    try:
                        await bot.send_message(lead.id, text, reply_markup=kb, parse_mode="HTML")
                        await repo.mark_meta_followup_step(session, lead.id, 1)
                        logger.info(f"Sent 1-hour Meta follow-up to user {lead.id}")
                    except (TelegramForbiddenError, TelegramBadRequest):
                        await repo.mark_meta_followup_step(session, lead.id, 99)
                    except Exception as exc:
                        logger.warning(f"Error sending 1h follow-up to {lead.id}: {exc}")
                    await asyncio.sleep(1.0)

                # 3. Check 24-hour leads (Step 1 -> Step 2)
                cutoff_24h = now - timedelta(hours=24)
                leads_24h = await repo.get_pending_meta_leads_for_followup(session, step=1, cutoff_time=cutoff_24h)

                for lead in leads_24h:
                    name = escape(lead.first_name or "there")
                    text = (
                        f"🎁 <b>Special 24-Hour Bonus for you, {name}!</b>\n\n"
                        "Complete your <b>Gemini AI Pro 18 Months (₹199)</b> order today and receive our exclusive "
                        "<b>AI Master Prompts & Workflows Bundle</b> (Value ₹1,499) completely free!\n\n"
                        "🔥 Includes 200+ curated prompts for coding, automated research, and creative workflows.\n\n"
                        "Tap below to claim your 5TB plan + bonus pack:"
                    )

                    buttons = []
                    if product_id:
                        buttons.append([InlineKeyboardButton(text=f"🎁 Claim Plan + Free Bonus (${product_price:.2f})", callback_data=f"paymenu:{product_id}:1")])
                    buttons.append([
                        InlineKeyboardButton(text="💬 Ask Questions", callback_data="help:home"),
                        InlineKeyboardButton(text="🏠 Main Menu", callback_data="home"),
                    ])
                    kb = InlineKeyboardMarkup(inline_keyboard=buttons)

                    try:
                        await bot.send_message(lead.id, text, reply_markup=kb, parse_mode="HTML")
                        await repo.mark_meta_followup_step(session, lead.id, 2)
                        logger.info(f"Sent 24-hour Meta follow-up to user {lead.id}")
                    except (TelegramForbiddenError, TelegramBadRequest):
                        await repo.mark_meta_followup_step(session, lead.id, 99)
                    except Exception as exc:
                        logger.warning(f"Error sending 24h follow-up to {lead.id}: {exc}")
                    await asyncio.sleep(1.0)

        except Exception as err:
            logger.exception(f"Unexpected error in meta_lead_recovery_worker: {err}")

        # Sleep for 3 minutes before checking again
        await asyncio.sleep(180)
