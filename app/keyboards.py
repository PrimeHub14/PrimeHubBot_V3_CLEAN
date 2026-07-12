from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from app.config import settings
from app.db.models import Product


def main_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🛍 Shop", callback_data="shop")],
        [InlineKeyboardButton(text="📦 My Orders", callback_data="myorders"), InlineKeyboardButton(text="⭐ Reviews", callback_data="reviews")],
    ]
    if settings.support_link:
        rows.append([InlineKeyboardButton(text="💬 Support", url=settings.support_link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def categories_kb(categories: list[str]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📂 {cat}", callback_data=f"cat:{cat}")] for cat in categories]
    rows += [[InlineKeyboardButton(text="🔥 All Products", callback_data="cat:__all__")], [InlineKeyboardButton(text="🏠 Home", callback_data="home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_list_kb(products: list[Product]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"🔥 {p.name} — ${float(p.price):.2f}", callback_data=f"product:{p.id}")] for p in products]
    rows += [[InlineKeyboardButton(text="📂 Categories", callback_data="shop")], [InlineKeyboardButton(text="🏠 Home", callback_data="home")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_kb(product_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="🛒 Choose Quantity", callback_data=f"quantity:{product_id}:1")], [InlineKeyboardButton(text="⬅️ Back to Store", callback_data="shop")]]
    if settings.support_link:
        rows.insert(1, [InlineKeyboardButton(text="💬 Ask Support", url=settings.support_link)])
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
        [InlineKeyboardButton(text="💰 Pay with Wallet", callback_data=f"manual:{product_id}:{quantity}:wallet")],
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
    if settings.support_link:
        rows.append([InlineKeyboardButton(text="💬 Payment Help", url=settings.support_link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def manual_payment_kb(order_id: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text="📤 I have paid — send proof below", callback_data=f"proofhelp:{order_id}")]]
    if settings.support_link:
        rows.append([InlineKeyboardButton(text="💬 Payment Help", url=settings.support_link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def admin_review_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve & Deliver", callback_data=f"adminapprove:{order_id}")],
        [InlineKeyboardButton(text="❌ Reject", callback_data=f"adminreject:{order_id}")],
    ])
