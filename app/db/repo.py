from datetime import datetime, timezone, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import uuid

from app.db.models import Order, Product, StockItem, User, SupportTicket, StockSubscription, Coupon, CouponRedemption, ReferralReward, LoyaltyTransaction, FlashSale

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


async def category_stock_totals(session: AsyncSession) -> tuple[dict[str, int], int]:
    """Return live available stock totals for each active category and all products."""
    stmt = (
        select(Product.category, func.count(StockItem.id))
        .select_from(Product)
        .outerjoin(
            StockItem,
            (StockItem.product_id == Product.id) & (StockItem.status == "available"),
        )
        .where(Product.active.is_(True))
        .group_by(Product.category)
        .order_by(Product.category)
    )
    rows = (await session.execute(stmt)).all()
    totals = {str(category): int(count or 0) for category, count in rows if category}
    return totals, sum(totals.values())


async def list_products_by_category(session: AsyncSession, category: str) -> list[Product]:
    stmt = select(Product).where(Product.active.is_(True), Product.category == category).order_by(Product.id.desc())
    return list((await session.execute(stmt)).scalars().all())


async def get_product(session: AsyncSession, product_id: int) -> Product | None:
    return await session.get(Product, product_id)


async def update_product_field(session: AsyncSession, product_id: int, field: str, value) -> Product | None:
    allowed = {"name", "price", "category", "description", "image", "delivery", "delivery_note", "delivery_mode"}
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


async def cancel_open_orders_for_user(session: AsyncSession, user_id: int) -> list[int]:
    """Cancel the user's older unpaid orders. Inventory is never held at checkout."""
    stmt = (
        select(Order)
        .where(
            Order.user_id == user_id,
            Order.delivered.is_(False),
            Order.status.in_(["pending", "awaiting_proof", "waiting_payment"]),
        )
        .with_for_update(skip_locked=True)
    )
    orders = list((await session.execute(stmt)).scalars().all())
    cancelled_ids: list[int] = []
    for order in orders:
        order.status = "cancelled"
        order.expires_at = None
        cancelled_ids.append(order.id)
    await session.commit()
    return cancelled_ids


async def cancel_order(session: AsyncSession, order_id: int, user_id: int | None = None) -> Order | None:
    """Cancel an unpaid order. No stock release is needed because stock is not held."""
    stmt = select(Order).where(Order.id == order_id).with_for_update()
    order = (await session.execute(stmt)).scalar_one_or_none()
    if not order or (user_id is not None and order.user_id != user_id):
        return None
    if order.status not in {"pending", "awaiting_proof", "waiting_payment"}:
        return order
    order.status = "cancelled"
    order.expires_at = None
    await session.commit()
    return order


async def create_order(session: AsyncSession, user_id: int, product: Product, currency: str,
                       payment_method: str | None = None, quantity: int = 1) -> Order:
    """Create an unpaid order without reserving inventory.

    Live inventory is claimed atomically only after payment is confirmed.
    """
    await cancel_open_orders_for_user(session, user_id)
    quantity = max(1, min(int(quantity), 13))
    if not product.stock_enabled:
        raise ValueError("This product is not configured for stock-controlled delivery")

    available = await available_stock_count(session, product.id)
    if available < quantity:
        raise ValueError(f"Only {available} item(s) are currently available. Please choose a lower quantity.")

    order = Order(
        user_id=user_id,
        product_id=product.id,
        amount=(await effective_price(session, user_id, product))[0] * quantity,
        quantity=quantity,
        currency=currency,
        payment_method=payment_method,
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)
    return order


async def set_order_payment_message(session: AsyncSession, order_id: int, chat_id: int, message_id: int, base_text: str) -> None:
    order = await session.get(Order, order_id)
    if order:
        order.payment_message_chat_id = chat_id
        order.payment_message_id = message_id
        order.payment_message_text = base_text
        await session.commit()


async def expire_unpaid_orders(session: AsyncSession) -> list[Order]:
    """Expire unpaid orders after the full payment window.

    Inventory is unaffected because checkout never reserves stock.
    """
    now = datetime.now(timezone.utc)
    stmt = select(Order).where(
        Order.expires_at.is_not(None),
        Order.expires_at <= now,
        Order.delivered.is_(False),
        Order.status.in_(["pending", "awaiting_proof", "waiting_payment"]),
    ).with_for_update(skip_locked=True)
    orders = list((await session.execute(stmt)).scalars().all())
    for order in orders:
        order.status = "expired"
    await session.commit()
    return orders


async def all_product_stock(session: AsyncSession) -> list[tuple[Product, int, int]]:
    """Return live available inventory. Third value remains 0 for compatibility."""
    products = await list_products(session, only_active=False)
    result = []
    for product in products:
        available = await available_stock_count(session, product.id)
        result.append((product, available, 0))
    return result


async def set_delivery_mode(session: AsyncSession, product_id: int, mode: str) -> Product | None:
    if mode not in {"instant", "manual"}:
        raise ValueError("Mode must be instant or manual")
    product = await session.get(Product, product_id)
    if not product:
        return None
    product.delivery_mode = mode
    product.stock_enabled = True
    await session.commit()
    await session.refresh(product)
    return product


async def add_manual_stock_slots(session: AsyncSession, product_id: int, quantity: int) -> int:
    quantity = max(1, int(quantity))
    items = [f"MANUAL-SLOT-{product_id}-{uuid.uuid4().hex}" for _ in range(quantity)]
    return await add_stock_items(session, product_id, items)

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
    order.expires_at = None
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
    stmt = (
        select(Order)
        .options(selectinload(Order.product))
        .where(Order.user_id == user_id)
        .order_by(Order.id.desc())
        .limit(limit)
    )
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


async def credit_wallet_topup(session: AsyncSession, topup) -> tuple[bool, Decimal]:
    """Credit a wallet top-up exactly once, even if approval is clicked twice."""
    from app.db.models import WalletTopUp
    stmt = select(WalletTopUp).where(WalletTopUp.id == topup.id).with_for_update()
    locked = (await session.execute(stmt)).scalar_one_or_none()
    if not locked or locked.credited:
        user = await session.get(User, topup.user_id)
        return False, Decimal(str(user.wallet_balance or 0)) if user else Decimal("0.00")
    user_stmt = select(User).where(User.id == locked.user_id).with_for_update()
    user = (await session.execute(user_stmt)).scalar_one_or_none()
    if not user:
        return False, Decimal("0.00")
    amount = Decimal(str(locked.amount)).quantize(Decimal("0.01"))
    current = Decimal(str(user.wallet_balance or 0)).quantize(Decimal("0.01"))
    user.wallet_balance = current + amount
    locked.credited = True
    locked.status = "credited"
    await session.commit()
    return True, Decimal(str(user.wallet_balance)).quantize(Decimal("0.01"))


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


# ---------- Prime Hub V4 growth helpers ----------
async def ensure_referral_code(session: AsyncSession, user_id: int) -> str:
    user = await session.get(User, user_id)
    if not user:
        raise ValueError("User not found")
    if not user.referral_code:
        user.referral_code = f"PH{user.id:x}".upper()
        await session.commit()
    return user.referral_code


async def set_referrer_from_code(session: AsyncSession, user_id: int, code: str) -> bool:
    user = await session.get(User, user_id)
    if not user or user.referrer_id or not code:
        return False
    stmt = select(User).where(User.referral_code == code.upper())
    referrer = (await session.execute(stmt)).scalar_one_or_none()
    if not referrer or referrer.id == user_id:
        return False
    user.referrer_id = referrer.id
    await session.commit()
    return True


async def referral_stats(session: AsyncSession, user_id: int) -> tuple[int, float]:
    invited = (await session.execute(select(func.count(User.id)).where(User.referrer_id == user_id))).scalar() or 0
    earned = (await session.execute(
        select(func.coalesce(func.sum(ReferralReward.amount), 0)).where(ReferralReward.referrer_id == user_id)
    )).scalar() or 0
    return int(invited), float(earned)


async def create_coupon(session: AsyncSession, code: str, percent_off: int, max_uses: int, expires_at):
    existing = (await session.execute(select(Coupon).where(Coupon.code == code.upper()))).scalar_one_or_none()
    if existing:
        existing.percent_off = percent_off
        existing.max_uses = max_uses
        existing.expires_at = expires_at
        existing.active = True
        coupon = existing
    else:
        coupon = Coupon(code=code.upper(), percent_off=percent_off, max_uses=max_uses, expires_at=expires_at)
        session.add(coupon)
    await session.commit()
    await session.refresh(coupon)
    return coupon


async def activate_coupon_for_user(session: AsyncSession, user_id: int, code: str) -> Coupon:
    now = datetime.now(timezone.utc)
    coupon = (await session.execute(select(Coupon).where(Coupon.code == code.upper(), Coupon.active.is_(True)))).scalar_one_or_none()
    if not coupon:
        raise ValueError("Coupon not found or inactive")
    if coupon.expires_at and coupon.expires_at <= now:
        raise ValueError("Coupon has expired")
    if coupon.max_uses > 0 and coupon.uses >= coupon.max_uses:
        raise ValueError("Coupon usage limit reached")
    user = await session.get(User, user_id)
    user.active_coupon_code = coupon.code
    await session.commit()
    return coupon


async def active_flash_sale(session: AsyncSession, product_id: int) -> FlashSale | None:
    now = datetime.now(timezone.utc)
    stmt = select(FlashSale).where(
        FlashSale.product_id == product_id,
        FlashSale.active.is_(True),
        FlashSale.starts_at <= now,
        FlashSale.ends_at > now,
    ).order_by(FlashSale.id.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def effective_price(session: AsyncSession, user_id: int, product: Product) -> tuple[float, str | None]:
    price = float(product.price)
    label = None
    sale = await active_flash_sale(session, product.id)
    if sale:
        price = min(price, float(sale.sale_price))
        label = "flash sale"
    user = await session.get(User, user_id)
    if user and user.active_coupon_code:
        try:
            coupon = (await session.execute(
                select(Coupon).where(Coupon.code == user.active_coupon_code, Coupon.active.is_(True))
            )).scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if coupon and (not coupon.expires_at or coupon.expires_at > now) and (coupon.max_uses == 0 or coupon.uses < coupon.max_uses):
                price = round(price * (100 - coupon.percent_off) / 100, 2)
                label = f"coupon {coupon.code}"
        except Exception:
            pass
    return max(price, 0.01), label


async def create_flash_sale(session: AsyncSession, product_id: int, sale_price: float, ends_at):
    await session.execute(update(FlashSale).where(FlashSale.product_id == product_id, FlashSale.active.is_(True)).values(active=False))
    sale = FlashSale(product_id=product_id, sale_price=sale_price, ends_at=ends_at, active=True)
    session.add(sale)
    await session.commit()
    await session.refresh(sale)
    return sale


async def recommendations(session: AsyncSession, user_id: int, limit: int = 5) -> list[Product]:
    recent = (await session.execute(
        select(Order).where(Order.user_id == user_id, Order.status == "delivered").order_by(Order.id.desc()).limit(5)
    )).scalars().all()
    categories = []
    for order in recent:
        product = await session.get(Product, order.product_id)
        if product and product.category not in categories:
            categories.append(product.category)
    stmt = select(Product).where(Product.active.is_(True))
    if categories:
        stmt = stmt.where(Product.category.in_(categories))
    stmt = stmt.order_by(Product.sold_count.desc(), Product.id.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars().all())


async def growth_dashboard(session: AsyncSession) -> dict:
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    total_users = (await session.execute(select(func.count(User.id)))).scalar() or 0
    total_orders = (await session.execute(select(func.count(Order.id)))).scalar() or 0
    delivered = (await session.execute(select(func.count(Order.id)).where(Order.status == "delivered"))).scalar() or 0
    pending = (await session.execute(select(func.count(Order.id)).where(Order.status.in_(["pending","awaiting_proof","proof_submitted"])))).scalar() or 0
    revenue = (await session.execute(select(func.coalesce(func.sum(Order.amount),0)).where(Order.status == "delivered"))).scalar() or 0
    today_revenue = (await session.execute(select(func.coalesce(func.sum(Order.amount),0)).where(Order.status == "delivered", Order.created_at >= day_start))).scalar() or 0
    open_tickets = (await session.execute(select(func.count(SupportTicket.id)).where(SupportTicket.status != "closed"))).scalar() or 0
    active_coupons = (await session.execute(select(func.count(Coupon.id)).where(Coupon.active.is_(True)))).scalar() or 0
    return {
        "users": int(total_users), "orders": int(total_orders), "delivered": int(delivered),
        "pending": int(pending), "revenue": float(revenue), "today_revenue": float(today_revenue),
        "open_tickets": int(open_tickets), "active_coupons": int(active_coupons),
    }


async def award_growth_rewards(session: AsyncSession, order: Order) -> None:
    """Idempotently award loyalty points, coupon use and referral commission."""
    user = await session.get(User, order.user_id)
    if not user:
        return
    existing_points = (await session.execute(
        select(LoyaltyTransaction).where(LoyaltyTransaction.order_id == order.id)
    )).scalar_one_or_none()
    if not existing_points:
        points = max(1, int(float(order.amount)))
        user.loyalty_points = int(user.loyalty_points or 0) + points
        session.add(LoyaltyTransaction(user_id=user.id, order_id=order.id, points=points, reason="Delivered order"))
        total = int(user.loyalty_points or 0)
        user.vip_tier = "Diamond" if total >= 1000 else "Gold" if total >= 500 else "Silver" if total >= 100 else "Bronze"

    if user.active_coupon_code:
        coupon = (await session.execute(select(Coupon).where(Coupon.code == user.active_coupon_code))).scalar_one_or_none()
        redemption = (await session.execute(select(CouponRedemption).where(CouponRedemption.order_id == order.id))).scalar_one_or_none()
        if coupon and not redemption:
            coupon.uses += 1
            session.add(CouponRedemption(coupon_id=coupon.id, user_id=user.id, order_id=order.id))
        user.active_coupon_code = None

    if user.referrer_id:
        existing_reward = (await session.execute(select(ReferralReward).where(ReferralReward.order_id == order.id))).scalar_one_or_none()
        if not existing_reward:
            commission = round(float(order.amount) * 0.03, 2)
            if commission > 0:
                referrer = await session.get(User, user.referrer_id)
                if referrer:
                    referrer.wallet_balance = float(referrer.wallet_balance or 0) + commission
                    session.add(ReferralReward(
                        referrer_id=referrer.id, referred_user_id=user.id, order_id=order.id, amount=commission
                    ))
    await session.commit()
