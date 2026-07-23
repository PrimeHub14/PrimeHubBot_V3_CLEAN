import asyncio, logging, os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from app.config import settings
from app.db.session import init_db
from app.handlers import admin, user, trc20
from app.services.tron_monitor import monitor_loop
from app.webhook import create_app

logging.basicConfig(level=logging.INFO)

async def start_bot() -> None:
    await init_db()
    bot = Bot(settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin.router)
    dp.include_router(trc20.router)
    dp.include_router(user.router)

    app = create_app(bot)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.environ.get("PORT", "8080"))).start()

    monitor = asyncio.create_task(monitor_loop(bot))
    logging.info("PrimeHub direct TRC20 verifier started")
    try:
        await dp.start_polling(bot)
    finally:
        monitor.cancel()
        try:
            await monitor
        except asyncio.CancelledError:
            pass

def main() -> None:
    asyncio.run(start_bot())

if __name__ == "__main__":
    main()
