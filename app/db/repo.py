from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.db.models import Order, Product, User

MANUAL_METHODS = {"wallet", "binance", "upi"}


async def upsert_user(session: AsyncSession, tg_user) -> User:
    user = await session.get(User, tg_user.id)
    if not user:
        user = User(id=tg_user.id, username=tg_user.username, first_name=tg_user.first_name)
        session.add(user)
    else:
        user.username = tg_user.username
        user.first_name = tg_user.first_name
    await session.commit()
    return user


async def create_product(session: AsyncSession, category: str, name: str, price: float, description: str,
                         delivery: str, is_file_id: bool, image_file_id: str | None = None) -> Product:
    product = Product(category=category, name=name, price=price, description=description,
                      delivery=delivery, is_file_id=is_file_id, image_file_id=image_file_id)
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


async def list_products(session: AsyncSession, only_active: bool = True) -> list[Product]:
    stmt = select(Product).order_by(Product.id.desc())
    if only_active:
        stmt = stmt.where(Product.active.is_(True))
    return list((await session.execute(stmt)).scalars().all())


async def list_categories(session: AsyncSession) -> list[str]:
    rows = (await session.execute(select(Product.category).where(Product.active.is_(True)).distinct().order_by(Product.category))).all()
    return [r[0] for r in rows if r[0]]


async def list_products_by_category(session: AsyncSession, category: str) -> list[Product]:
    stmt = select(Product).where(Product.active.is_(True), Product.category == category).order_by(Product.id.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_product(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)


async def update_product_field(session: AsyncSession, product_id: int, field: str, value) -> Product | None:
    allowed = {"name", "price", "category", "description", "image", "delivery"}
    if field not in allowed:
        raise ValueError("Unsupported product field")
    product = await session.get(Product, product_id)
    if not product:
        return None
    model_field = "image_file_id" if field == "image" else field
    setattr(product, model_field, value)
    await session.commit()
    await session.refresh(product)
    return product


async def toggle_product_active(session: AsyncSession, product_id: int) -> Product | None:
    product = await session.get(Product, product_id)
    if not product:
        return None
    product.active = not product.active
    await session.commit()
    await session.refresh(product)
    return product


async def deactivate_product(session: AsyncSession, product_id: int) -> bool:
    product = await session.get(Product, product_id)
    if not product:
        return False
    product.active = False
    await session.commit()
    return True


async def create_order(session: AsyncSession, user_id: int, product: Product, currency: str,
                       payment_method: str | None = None, quantity: int = 1) -> Order:
    quantity = max(1, min(int(quantity), 13))
    order = Order(user_id=user_id, product_id=product.id,
                  amount=float(product.price) * quantity, quantity=quantity,
                  currency=currency, payment_method=payment_method, status="pending")
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def get_order_with_product(session: AsyncSession, order_id: int) -> Order | None:
    stmt = select(Order).options(selectinload(Order.product), selectinload(Order.user)).where(Order.id == order_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_order_invoice(session: AsyncSession, order_id: int, payment_id: str, invoice_url: str) -> None:
    order = await session.get(Order, order_id)
    if order:
        order.provider_payment_id = payment_id
        order.invoice_url = invoice_url
        await session.commit()


async def latest_manual_order_waiting_for_proof(session: AsyncSession, user_id: int) -> Order | None:
    stmt = (
        select(Order)
        .options(selectinload(Order.product), selectinload(Order.user))
        .where(
            Order.user_id == user_id,
            Order.payment_method.in_(MANUAL_METHODS),
            Order.status.in_(["pending", "awaiting_proof"]),
        )
        .order_by(Order.id.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def save_payment_proof(session: AsyncSession, order: Order, proof_type: str, proof_value: str) -> None:
    order.payment_proof_type = proof_type
    order.payment_proof_value = proof_value
    order.status = "proof_submitted"
    await session.commit()


async def set_order_status(session: AsyncSession, order: Order, status: str) -> None:
    order.status = status
    await session.commit()


async def mark_delivered(session: AsyncSession, order: Order) -> None:
    order.delivered = True
    order.status = "delivered"
    product = await session.get(Product, order.product_id)
    if product:
        product.sold_count = (product.sold_count or 0) + max(1, order.quantity or 1)
    await session.commit()


async def recent_orders(session: AsyncSession, limit: int = 10) -> list[Order]:
    stmt = select(Order).order_by(Order.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def user_orders(session: AsyncSession, user_id: int, limit: int = 10) -> list[Order]:
    stmt = select(Order).where(Order.user_id == user_id).order_by(Order.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def stats(session: AsyncSession) -> tuple[int, int, float]:
    users = (await session.execute(select(func.count(User.id)))).scalar() or 0
    orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    revenue = (await session.execute(select(func.coalesce(func.sum(Order.amount), 0)).where(Order.status == "delivered"))).scalar() or 0
    return int(users), int(orders), float(revenue)
