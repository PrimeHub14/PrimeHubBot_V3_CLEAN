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
    rows = [[InlineKeyboardButton(text="💳 Choose Payment Method", callback_data=f"paymenu:{product_id}")], [InlineKeyboardButton(text="⬅️ Back to Store", callback_data="shop")]]
    if settings.support_link:
        rows.insert(1, [InlineKeyboardButton(text="💬 Ask Support", url=settings.support_link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_kb(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Pay with Wallet", callback_data=f"manual:{product_id}:wallet")],
        [InlineKeyboardButton(text="🟡 Pay with Binance", callback_data=f"manual:{product_id}:binance")],
        [InlineKeyboardButton(text="⚪ Pay with USDT (BEP20)", callback_data=f"paycoin:{product_id}:usdtbep20")],
        [InlineKeyboardButton(text="⚪ Pay with USDT (TRC20)", callback_data=f"paycoin:{product_id}:usdttrc20")],
        [InlineKeyboardButton(text="⚪ Pay with UPI", callback_data=f"manual:{product_id}:upi")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"product:{product_id}")],
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
