from decimal import Decimal

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User


async def debit_wallet(session: AsyncSession, user_id: int, amount: float) -> bool:
    amount_d = Decimal(str(round(float(amount), 2)))
    result = await session.execute(
        update(User)
        .where(User.id == user_id, User.wallet_balance >= amount_d)
        .values(wallet_balance=User.wallet_balance - amount_d)
    )
    if result.rowcount != 1:
        await session.rollback()
        return False
    await session.commit()
    return True


async def credit_wallet(session: AsyncSession, user_id: int, amount: float) -> None:
    amount_d = Decimal(str(round(float(amount), 2)))
    await session.execute(
        update(User).where(User.id == user_id).values(wallet_balance=User.wallet_balance + amount_d)
    )
    await session.commit()
