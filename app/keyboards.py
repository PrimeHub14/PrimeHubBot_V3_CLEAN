from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings
from app.i18n import tr
from app.db.models import Product


def main_menu_kb(lang: str = "en") -> InlineKeyboardMarkup:
    """Prime Hub customer home menu — locked to the preferred compact layout."""
    rows = [
        [InlineKeyboardButton(text="🛍 Shop", callback_data="shop")],
        [InlineKeyboardButton(text="💰 Wallet", callback_data="wallet:home")],
        [
            InlineKeyboardButton(text="📦 Order History", callback_data="myorders"),
            InlineKeyboardButton(text="⭐ Reviews", callback_data="reviews"),
        ],
        [
            InlineKeyboardButton(text="🎁 Referral", callback_data="growth:referral"),
            InlineKeyboardButton(text="🏆 Loyalty", callback_data="growth:loyalty"),
        ],
        [
            InlineKeyboardButton(text="🌍 Language", callback_data="v5:language"),
            InlineKeyboardButton(text="🛟 Support", callback_data="help:home"),
        ],
    ]
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
    rows += [
        [InlineKeyboardButton(text="📂 Categories", callback_data="shop")],
        [InlineKeyboardButton(text="🏠 Home", callback_data="home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def product_kb(product_id: int, available_stock: int = 0) -> InlineKeyboardMarkup:
    if available_stock > 0:
        rows = [
            [InlineKeyboardButton(text="🛒 Choose Quantity", callback_data=f"quantity:{product_id}:1")],
            [
                InlineKeyboardButton(text="❤️ Wishlist", callback_data=f"v5:wishlisttoggle:{product_id}"),
                InlineKeyboardButton(text="⭐ Reviews", callback_data="reviews"),
            ],
            [InlineKeyboardButton(text="🔔 Restock Alerts", callback_data=f"stocknotify:{product_id}")],
            [InlineKeyboardButton(text="⬅️ Back to Store", callback_data="shop")],
        ]
    else:
        rows = [
            [InlineKeyboardButton(text="❌ Out of Stock", callback_data="outofstock")],
            [
                InlineKeyboardButton(text="❤️ Wishlist", callback_data=f"v5:wishlisttoggle:{product_id}"),
                InlineKeyboardButton(text="⭐ Reviews", callback_data="reviews"),
            ],
            [InlineKeyboardButton(text="🔔 Notify Me When Restocked", callback_data=f"stocknotify:{product_id}")],
            [InlineKeyboardButton(text="⬅️ Back to Store", callback_data="shop")],
        ]
    if settings.support_link:
        rows.insert(-1, [InlineKeyboardButton(text="💬 Ask Support", url=settings.support_link)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def quantity_kb(product_id: int, quantity: int) -> InlineKeyboardMarkup:
    quantity = max(1, int(quantity))
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="➖", callback_data=f"qty:{product_id}:{quantity}:-1"),
            InlineKeyboardButton(text=f"{quantity}", callback_data="qtynoop"),
            InlineKeyboardButton(text="➕", callback_data=f"qty:{product_id}:{quantity}:1"),
        ],
        [InlineKeyboardButton(text="⌨️ Type Quantity", callback_data=f"typeqty:{product_id}")],
        [InlineKeyboardButton(text="✅ Continue to Payment", callback_data=f"paymenu:{product_id}:{quantity}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"product:{product_id}")],
    ])


def payment_methods_kb(product_id: int, quantity: int = 1) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Pay with Wallet", callback_data=f"walletpay:{product_id}:{quantity}")],
        [InlineKeyboardButton(text="🟡 Pay with Binance — Auto Verify", callback_data=f"directbinance:{product_id}:{quantity}")],
        [InlineKeyboardButton(text="🟡 Pay with USDT (BEP20) — Auto Verify", callback_data=f"directbep:{product_id}:{quantity}")],
        [InlineKeyboardButton(text="🟢 Pay with USDT (TRC20) — Auto Verify", callback_data=f"directtrc:{product_id}:{quantity}")],
        [InlineKeyboardButton(text="🇮🇳 Pay with UPI — Auto Verify", callback_data=f"directupi:{product_id}:{quantity}")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data=f"quantity:{product_id}:{quantity}")],
    ])


def upi_waiting_kb(order_id: int) -> InlineKeyboardMarkup:
    """Buttons shown under UPI auto-verification card."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✍️ Submit 12-Digit UTR", callback_data=f"submitutr:{order_id}")],
            [InlineKeyboardButton(text="🔄 Check Status", callback_data=f"checkupi:{order_id}")],
            [InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"cancelupi:{order_id}")],
            [InlineKeyboardButton(text="🛟 Payment Help", callback_data="help:home")],
        ]
    )


def binance_waiting_kb(order_id: int) -> InlineKeyboardMarkup:
    """Buttons shown under Binance Pay auto-verification card."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Check Payment Status", callback_data=f"binancecheck:{order_id}")],
            [InlineKeyboardButton(text="✍️ Submit Binance Order ID / TxID", callback_data=f"binancetxid:{order_id}")],
            [InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"binancecancel:{order_id}")],
            [InlineKeyboardButton(text="🛟 Payment Help", callback_data="help:home")],
        ]
    )


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


def crypto_waiting_kb(order_id: int) -> InlineKeyboardMarkup:
    """Buttons shown under direct TRC20/BEP20 payment QR cards."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel Order", callback_data=f"cancelorder:{order_id}")],
            [InlineKeyboardButton(text="💬 Payment Help", callback_data="help:home")],
        ]
    )




def order_history_kb(orders) -> InlineKeyboardMarkup:
    rows = []
    for order in orders:
        product_name = order.product.name if getattr(order, "product", None) else f"Product {order.product_id}"
        price = float(order.amount)
        rows.append([
            InlineKeyboardButton(
                text=f"📦 #{order.id} · {product_name[:28]} · ${price:.2f}",
                callback_data=f"orderhistory:{order.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(inline_keyboard=rows)



def order_again_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Shop / Order Again", callback_data="shop")],
        [InlineKeyboardButton(text="🏠 Home", callback_data="home")],
    ])


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
        [InlineKeyboardButton(text="🇮🇳 UPI", callback_data=f"wtopup:{a}:upi")],
        [InlineKeyboardButton(text="🟡 USDT (BEP20)", callback_data=f"wtopup:{a}:usdtbep20")],
        [InlineKeyboardButton(text="🟢 USDT (TRC20)", callback_data=f"wtopup:{a}:usdttrc20")],
        [InlineKeyboardButton(text="⬅️ Back", callback_data="wallet:add")],
    ])


def wallet_proof_kb(topup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 I have paid — send proof", callback_data=f"wproof:{topup_id}")]
        ]
    )


def admin_wallet_review_kb(topup_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Approve Wallet Top-up", callback_data=f"wapprove:{topup_id}")],
        [InlineKeyboardButton(text="❌ Reject", callback_data=f"wreject:{topup_id}")],
    ])


def manual_delivery_admin_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Send Manual Delivery", callback_data=f"manualdeliver:{order_id}")]
        ]
    )
