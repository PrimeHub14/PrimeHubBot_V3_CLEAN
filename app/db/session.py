from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from app.config import settings
from app.db.models import Base

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Safe migrations for existing Railway PostgreSQL databases.
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS wallet_balance NUMERIC(12,2) DEFAULT 0 NOT NULL"))
        await conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS category VARCHAR(255) DEFAULT 'Digital Products'"))
        await conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_file_id TEXT"))
        await conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS sold_count INTEGER DEFAULT 0"))
        await conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS stock_enabled BOOLEAN DEFAULT FALSE"))
        await conn.execute(text("ALTER TABLE products ADD COLUMN IF NOT EXISTS delivery_note TEXT DEFAULT '' NOT NULL"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(50)"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS quantity INTEGER DEFAULT 1 NOT NULL"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_proof_type VARCHAR(30)"))
        await conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_proof_value TEXT"))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_subscription_user_product "
            "ON stock_subscriptions (user_id, product_id)"
        ))
