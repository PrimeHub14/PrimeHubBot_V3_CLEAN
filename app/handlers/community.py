from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal
from app.services.announcements import send_to_update_chats
from app.utils.security import is_admin

router = Router()


@router.callback_query(F.data.startswith("stocknotify:"))
async def restock_alert(call: CallbackQuery):
    product_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
        if not product:
            await call.answer("Product not found.", show_alert=True)
            return
        changed = await repo.subscribe_restock(session, call.from_user.id, product_id)
    await call.answer(
        "Restock alerts enabled." if changed else "You are already subscribed.",
        show_alert=True,
    )


@router.message(Command("community"))
async def community_command(message: Message):
    if settings.community_link:
        await message.answer(f"📢 Prime Hub updates: {settings.community_link}")
    else:
        await message.answer("The Prime Hub updates group is not configured yet.")


@router.message(Command("announce"))
async def announce_command(message: Message):
    if not message.from_user or not is_admin(message.from_user.id):
        return
    text = (message.text or "").partition(" ")[2].strip()
    if not text:
        await message.answer("Usage: /announce Your update message")
        return
    if not settings.update_chat_ids():
        await message.answer("UPDATE_CHAT_IDS is not configured in Railway.")
        return
    sent, failed = await send_to_update_chats(
        message.bot,
        f"📢 <b>Prime Hub Update</b>\n\n{text}",
    )
    await message.answer(f"✅ Sent to {sent} update chat(s). Failed: {failed}.")
