from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.config import settings
from app.db.models import Product


def main_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🛍 Shop", callback_data="shop")],
        [InlineKeyboardButton(text="💰 My Wallet", callback_data="wallet:home")],
        [InlineKeyboardButton(text="📦 My Orders", callback_data="myorders"), InlineKeyboardButton(text="⭐ Reviews", callback_data="reviews")],
        [InlineKeyboardButton(text="🎁 Referral", callback_data="growth:referral"), InlineKeyboardButton(text="🏆 Loyalty", callback_data="growth:loyalty")],
        [InlineKeyboardButton(text="🧠 Recommendations", callback_data="growth:recommend"), InlineKeyboardButton(text="🛟 Help", callback_data="help:home")],
    ]
    if settings.community_link:
        rows.append([InlineKeyboardButton(text="📢 Prime Hub Updates", url=settings.community_link)])
    if settings.support_link:
        rows.append([InlineKeyboardButton(text="💬 Support", url=settings.support_link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_kb(
    categories: list[str],
    stock_totals: dict[str, int] | None = None,
    all_stock: int = 0,
) -> InlineKeyboardMarkup:
    stock_totals = stock_totals or {}
    rows = [
        [
            InlineKeyboardButton(
                text=f"📂 {cat} · Stock: {int(stock_totals.get(cat, 0))}",
                callback_data=f"cat:{cat}",
            )
        ]
        for cat in categories
    ]
    rows += [
        [InlineKeyboardButton(text=f"🔥 All Products · Stock: {int(all_stock)}", callback_data="cat:__all__")],
        [InlineKeyboardButton(text="🏠 Home", callback_data="home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_list_kb(products: list[Product], stock_counts: dict[int, int] | None = None) -> InlineKeyboardMarkup:
    stock_counts = stock_counts or {}
    rows = []
    for p in products:
        stock = int(stock_counts.get(p.id, 0))
        if stock > 0:
            label = f"🟢 {p.name} — ${float(p.price):.2f} | Stock: {stock}"
        else:
            label = f"🔴 {p.name} — ${float(p.price):.2f} | OUT OF STOCK"
        rows.append([InlineKeyboardButton(text=label, callback_data=f"product:{p.id}")])
    rows += [[InlineKeyboardButton(text="📂 Categories", callback_data="shop")], [InlineKeyboardButton(text="🏠 Home", callback_data="home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_kb(product_id: int, available_stock: int = 0) -> InlineKeyboardMarkup:
    if available_stock > 0:
        rows = [
            [InlineKeyboardButton(text="🛒 Choose Quantity", callback_data=f"quantity:{product_id}:1")],
            [InlineKeyboardButton(text="🔔 Restock Alerts", callback_data=f"stocknotify:{product_id}")],
            [InlineKeyboardButton(text="⬅️ Back to Store", callback_data="shop")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="❌ Out of Stock", callback_data="outofstock")],
            [InlineKeyboardButton(text="🔔 Notify Me When Restocked", callback_data=f"stocknotify:{product_id}")],
            [InlineKeyboardButton(text="⬅️ Back to Store", callback_data="shop")],
        ]
    if settings.support_link:
        rows.insert(-1, [InlineKeyboardButton(text="💬 Ask Support", url=settings.support_link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quantity_kb(product_id: int, quantity: int) -> InlineKeyboardMarkup:
    quantity = max(1, min(quantity, 13))
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➖", callback_data=f"qty:{product_id}:{quantity}:-1"),
            InlineKeyboardButton(text=f"{quantity}", callback_data="qtynoop"),
            InlineKeyboardButton(text="➕", callback_data=f"qty:{product_id}:{quantity}:1"),
        ],
        [InlineKeyboardButton(text="✅ Continue to Payment", callback_data=f"paymenu:{product_id}:{quantity}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"product:{product_id}")],
    ])


def payment_methods_kb(product_id: int, quantity: int = 1) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Pay with Wallet", callback_data=f"walletpay:{product_id}:{quantity}")],
        [InlineKeyboardButton(text="🟡 Pay with Binance", callback_data=f"manual:{product_id}:{quantity}:binance")],
        [InlineKeyboardButton(text="⚪ Pay with USDT (BEP20)", callback_data=f"paycoin:{product_id}:{quantity}:usdtbep20")],
        [InlineKeyboardButton(text="⚪ Pay with USDT (TRC20)", callback_data=f"paycoin:{product_id}:{quantity}:usdttrc20")],
        [InlineKeyboardButton(text="⚪ Pay with UPI", callback_data=f"manual:{product_id}:{quantity}:upi")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"quantity:{product_id}:{quantity}")],
    ])


def payment_info_kb(payment_url: str | None = None) -> InlineKeyboardMarkup:
    rows = []
    if payment_url:
        rows.append([InlineKeyboardButton(text="Open backup payment page", url=payment_url)])
    rows.append([InlineKeyboardButton(text="🔄 Payment checks automatically", callback_data="paid:info")])
    rows.append([InlineKeyboardButton(text="🛟 Payment Help", callback_data="help:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manual_payment_kb(order_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="📤 I have paid — send proof below", callback_data=f"proofhelp:{order_id}")],
        [InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"cancelorder:{order_id}")],
    ]
    rows.append([InlineKeyboardButton(text="🛟 Payment Help", callback_data="help:home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_review_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve & Deliver", callback_data=f"adminapprove:{order_id}")],
        [InlineKeyboardButton(text="❌ Reject", callback_data=f"adminreject:{order_id}")],
    ])


def wallet_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add Funds", callback_data="wallet:add")],
        [InlineKeyboardButton(text="🛍 Shop", callback_data="shop")],
        [InlineKeyboardButton(text="🏠 Home", callback_data="home")],
    ])


def wallet_amount_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="$5", callback_data="wamount:5"), InlineKeyboardButton(text="$10", callback_data="wamount:10")],
        [InlineKeyboardButton(text="$20", callback_data="wamount:20"), InlineKeyboardButton(text="$50", callback_data="wamount:50")],
        [InlineKeyboardButton(text="✏️ Custom Amount", callback_data="wamount:custom")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="wallet:home")],
    ])


def wallet_topup_methods_kb(amount: float) -> InlineKeyboardMarkup:
    a = f"{float(amount):.2f}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟡 Binance Pay", callback_data=f"wtopup:{a}:binance")],
        [InlineKeyboardButton(text="⚪ UPI", callback_data=f"wtopup:{a}:upi")],
        [InlineKeyboardButton(text="⚪ USDT (BEP20)", callback_data=f"wtopup:{a}:usdtbep20")],
        [InlineKeyboardButton(text="⚪ USDT (TRC20)", callback_data=f"wtopup:{a}:usdttrc20")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="wallet:add")],
    ])


def wallet_proof_kb(topup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📤 I have paid — send proof", callback_data=f"wproof:{topup_id}")]])


def admin_wallet_review_kb(topup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve Wallet Top-up", callback_data=f"wapprove:{topup_id}")],
        [InlineKeyboardButton(text="❌ Reject", callback_data=f"wreject:{topup_id}")],
    ])


def manual_delivery_admin_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📦 Send Manual Delivery", callback_data=f"manualdeliver:{order_id}")]])
