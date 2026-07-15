from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Order, Product, StockItem, User, SupportTicket, StockSubscription

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
    allowed = {"name", "price", "category", "description", "image", "delivery", "delivery_note"}
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


async def available_stock_count(session: AsyncSession, product_id: int) -> int:
    stmt = select(func.count(StockItem.id)).where(
        StockItem.product_id == product_id,
        StockItem.status == "available",
    )
    return int((await session.execute(stmt)).scalar() or 0)


async def add_stock_items(session: AsyncSession, product_id: int, items: list[str], is_file_id: bool = False) -> int:
    product = await session.get(Product, product_id)
    if not product:
        raise ValueError("Product not found")
    cleaned = [item.strip() for item in items if item and item.strip()]
    if not cleaned:
        return 0
    session.add_all([
        StockItem(product_id=product_id, content=item, is_file_id=is_file_id, status="available")
        for item in cleaned
    ])
    product.stock_enabled = True
    await session.commit()
    return len(cleaned)


async def remove_available_stock(session: AsyncSession, product_id: int, quantity: int) -> int:
    quantity = max(1, int(quantity))
    stmt = (
        select(StockItem)
        .where(StockItem.product_id == product_id, StockItem.status == "available")
        .order_by(StockItem.id.desc())
        .limit(quantity)
        .with_for_update(skip_locked=True)
    )
    items = list((await session.execute(stmt)).scalars().all())
    for item in items:
        await session.delete(item)
    await session.commit()
    return len(items)


async def disable_stock_mode(session: AsyncSession, product_id: int) -> bool:
    product = await session.get(Product, product_id)
    if not product:
        return False
    product.stock_enabled = False
    await session.commit()
    return True


async def allocate_stock_items(session: AsyncSession, order: Order) -> list[StockItem]:
    """Return stock already reserved for this order; reserve only as a fallback."""
    quantity = max(1, int(order.quantity or 1))
    reserved_stmt = (
        select(StockItem)
        .where(
            StockItem.product_id == order.product_id,
            StockItem.reserved_order_id == order.id,
            StockItem.status == "reserved",
        )
        .order_by(StockItem.id.asc())
    )
    reserved = list((await session.execute(reserved_stmt)).scalars().all())
    if len(reserved) == quantity:
        return reserved

    stmt = (
        select(StockItem)
        .where(
            StockItem.product_id == order.product_id,
            StockItem.status == "available",
        )
        .order_by(StockItem.id.asc())
        .limit(quantity)
        .with_for_update(skip_locked=True)
    )
    items = list((await session.execute(stmt)).scalars().all())
    if len(items) != quantity:
        await session.rollback()
        return []
    for item in items:
        item.status = "reserved"
        item.reserved_order_id = order.id
    await session.commit()
    return items


async def complete_stock_items(session: AsyncSession, order_id: int) -> None:
    stmt = select(StockItem).where(StockItem.reserved_order_id == order_id, StockItem.status == "reserved")
    items = list((await session.execute(stmt)).scalars().all())
    now = datetime.now(timezone.utc)
    for item in items:
        item.status = "delivered"
        item.delivered_at = now
    await session.commit()


async def release_stock_items(session: AsyncSession, order_id: int) -> None:
    stmt = select(StockItem).where(StockItem.reserved_order_id == order_id, StockItem.status == "reserved")
    items = list((await session.execute(stmt)).scalars().all())
    for item in items:
        item.status = "available"
        item.reserved_order_id = None
    await session.commit()


async def create_order(session: AsyncSession, user_id: int, product: Product, currency: str,
                       payment_method: str | None = None, quantity: int = 1) -> Order:
    """Create an order and atomically reserve one unique stock row per quantity."""
    quantity = max(1, min(int(quantity), 13))
    if not product.stock_enabled:
        raise ValueError("This product is not configured for stock-controlled delivery")

    order = Order(
        user_id=user_id,
        product_id=product.id,
        amount=float(product.price) * quantity,
        quantity=quantity,
        currency=currency,
        payment_method=payment_method,
        status="pending",
    )
    session.add(order)
    await session.flush()

    stmt = (
        select(StockItem)
        .where(StockItem.product_id == product.id, StockItem.status == "available")
        .order_by(StockItem.id.asc())
        .limit(quantity)
        .with_for_update(skip_locked=True)
    )
    items = list((await session.execute(stmt)).scalars().all())
    if len(items) != quantity:
        await session.rollback()
        available = await available_stock_count(session, product.id)
        raise ValueError(f"Only {available} item(s) are available. Please choose a lower quantity.")

    for item in items:
        item.status = "reserved"
        item.reserved_order_id = order.id

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


# Internal wallet and top-up helpers
async def wallet_balance(session: AsyncSession, user_id: int) -> float:
    user = await session.get(User, user_id)
    return float(user.wallet_balance or 0) if user else 0.0


async def create_wallet_topup(session: AsyncSession, user_id: int, amount: float, method: str):
    from app.db.models import WalletTopUp
    topup = WalletTopUp(user_id=user_id, amount=amount, method=method, status="pending")
    session.add(topup)
    await session.commit()
    await session.refresh(topup)
    return topup


async def get_wallet_topup(session: AsyncSession, topup_id: int):
    from app.db.models import WalletTopUp
    return await session.get(WalletTopUp, topup_id)


async def set_wallet_topup_invoice(session: AsyncSession, topup_id: int, payment_id: str) -> None:
    from app.db.models import WalletTopUp
    topup = await session.get(WalletTopUp, topup_id)
    if topup:
        topup.provider_payment_id = payment_id
        topup.status = "waiting_payment"
        await session.commit()


async def latest_wallet_topup_waiting_for_proof(session: AsyncSession, user_id: int):
    from app.db.models import WalletTopUp
    stmt = select(WalletTopUp).where(
        WalletTopUp.user_id == user_id,
        WalletTopUp.method.in_(["binance", "upi"]),
        WalletTopUp.status.in_(["pending", "awaiting_proof"]),
    ).order_by(WalletTopUp.id.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def save_wallet_topup_proof(session: AsyncSession, topup, proof_type: str, proof_value: str) -> None:
    topup.payment_proof_type = proof_type
    topup.payment_proof_value = proof_value
    topup.status = "proof_submitted"
    await session.commit()


async def credit_wallet_topup(session: AsyncSession, topup) -> bool:
    if topup.credited:
        return False
    user = await session.get(User, topup.user_id)
    if not user:
        return False
    user.wallet_balance = float(user.wallet_balance or 0) + float(topup.amount)
    topup.credited = True
    topup.status = "credited"
    await session.commit()
    return True


# Support tickets
async def create_support_ticket(
    session: AsyncSession,
    user_id: int,
    issue_type: str,
    message: str,
    order_id: int | None = None,
    attachment_file_id: str | None = None,
) -> SupportTicket:
    ticket = SupportTicket(
        user_id=user_id,
        order_id=order_id,
        issue_type=issue_type,
        message=message,
        attachment_file_id=attachment_file_id,
        status="open",
    )
    session.add(ticket)
    await session.commit()
    await session.refresh(ticket)
    return ticket


async def get_support_ticket(session: AsyncSession, ticket_id: int) -> SupportTicket | None:
    return await session.get(SupportTicket, ticket_id)


async def user_support_tickets(session: AsyncSession, user_id: int, limit: int = 10) -> list[SupportTicket]:
    stmt = (
        select(SupportTicket)
        .where(SupportTicket.user_id == user_id)
        .order_by(SupportTicket.id.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def reply_support_ticket(session: AsyncSession, ticket: SupportTicket, reply: str) -> None:
    ticket.admin_reply = reply
    ticket.status = "answered"
    await session.commit()


async def close_support_ticket(session: AsyncSession, ticket: SupportTicket) -> None:
    ticket.status = "closed"
    ticket.closed_at = datetime.now(timezone.utc)
    await session.commit()


# Restock subscriptions
async def subscribe_restock(session: AsyncSession, user_id: int, product_id: int) -> bool:
    stmt = select(StockSubscription).where(
        StockSubscription.user_id == user_id,
        StockSubscription.product_id == product_id,
    )
    subscription = (await session.execute(stmt)).scalar_one_or_none()
    if subscription:
        changed = not subscription.active
        subscription.active = True
        await session.commit()
        return changed
    session.add(StockSubscription(user_id=user_id, product_id=product_id, active=True))
    await session.commit()
    return True


async def unsubscribe_restock(session: AsyncSession, user_id: int, product_id: int) -> bool:
    stmt = select(StockSubscription).where(
        StockSubscription.user_id == user_id,
        StockSubscription.product_id == product_id,
    )
    subscription = (await session.execute(stmt)).scalar_one_or_none()
    if not subscription or not subscription.active:
        return False
    subscription.active = False
    await session.commit()
    return True


async def restock_subscribers(session: AsyncSession, product_id: int) -> list[int]:
    stmt = select(StockSubscription.user_id).where(
        StockSubscription.product_id == product_id,
        StockSubscription.active.is_(True),
    )
    return [int(row[0]) for row in (await session.execute(stmt)).all()]
