from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from app.config import settings
from app.db import repo
from app.db.session import SessionLocal


def is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids_set


class BlockedUserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user and not is_admin(user.id):
            async with SessionLocal() as session:
                is_blocked = await repo.is_user_blocked(session, user.id)
            if is_blocked:
                support_user = (settings.SUPPORT_USERNAME or "PrimeHubSupport").lstrip("@")
                msg_text = (
                    "⚠️ <b>Access Suspended</b>\n\n"
                    "Your access to Prime Hub has been suspended by the administrator due to unusual activity.\n"
                    f"If you believe this is an error, please contact support @{support_user}."
                )
                if isinstance(event, Message):
                    try:
                        await event.answer(msg_text, parse_mode="HTML")
                    except Exception:
                        pass
                elif isinstance(event, CallbackQuery):
                    try:
                        await event.answer("⚠️ Your account has been suspended by the administrator.", show_alert=True)
                    except Exception:
                        pass
                return None

        return await handler(event, data)

