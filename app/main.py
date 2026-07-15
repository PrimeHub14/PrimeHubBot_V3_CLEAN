import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.db.session import init_db
from app.handlers import admin, navigation, wallet, user, support, assistant, community
from app.webhook import create_app
from app.services.order_expiry import order_expiry_worker

logging.basicConfig(level=logging.INFO)


async def start_bot() -> None:
    await init_db()

    bot = Bot(settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Navigation must be registered first so /start, /menu, /shop,
    # /wallet, /orders, /profile and /help work from any active flow.
    dp.include_router(navigation.router)
    dp.include_router(support.router)
    dp.include_router(assistant.router)
    dp.include_router(community.router)
    dp.include_router(admin.router)
    dp.include_router(wallet.router)
    dp.include_router(user.router)

    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(
        runner,
        "0.0.0.0",
        int(os.environ.get("PORT", "8080")),
    )
    await site.start()

    logging.info("PrimeHub Premium Store V2 started.")
    expiry_task = asyncio.create_task(order_expiry_worker(bot))
    try:
        await dp.start_polling(bot)
    finally:
        expiry_task.cancel()


def main() -> None:
    asyncio.run(start_bot())


if __name__ == "__main__":
    main()
