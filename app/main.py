import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from app.config import settings
from app.db.session import init_db
from app.handlers import (
    admin,
    navigation,
    wallet,
    user,
    support,
    assistant,
    community,
    growth,
    trc20,
)
from app.webhook import create_app
from app.services.order_expiry import order_expiry_worker
from app.services.tron_monitor import monitor_loop

logging.basicConfig(level=logging.INFO)


async def start_bot() -> None:
    await init_db()

    bot = Bot(settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Navigation first so global commands work from any active flow.
    dp.include_router(navigation.router)
    dp.include_router(support.router)
    dp.include_router(assistant.router)
    dp.include_router(community.router)
    dp.include_router(growth.router)
    dp.include_router(admin.router)
    dp.include_router(wallet.router)

    # Direct TRC20 callback must be registered before the general user router.
    dp.include_router(trc20.router)
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

    logging.info("Prime Hub V3 started with direct TRC20 auto verification.")

    expiry_task = asyncio.create_task(order_expiry_worker(bot))
    trc20_task = asyncio.create_task(monitor_loop(bot))

    try:
        await dp.start_polling(bot)
    finally:
        expiry_task.cancel()
        trc20_task.cancel()
        await asyncio.gather(expiry_task, trc20_task, return_exceptions=True)


def main() -> None:
    asyncio.run(start_bot())


if __name__ == "__main__":
    main()
