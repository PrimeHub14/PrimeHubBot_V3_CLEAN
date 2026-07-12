from aiogram import F, Router
from aiogram.filters import CommandStart, Command
from aiogram.types import CallbackQuery, Message
from app.config import settings
from app.db.session import SessionLocal
from app.db import repo
from app.keyboards import (
    main_menu_kb,
    categories_kb,
    product_list_kb,
    product_kb,
    payment_methods_kb,
    payment_info_kb,
    manual_payment_kb,
    admin_review_kb,
)
from app.services.nowpayments import NowPayments

router = Router()

PAYMENT_LABELS = {
    "usdttrc20": "⚪ USDT (TRC20)",
    "usdtbep20": "⚪ USDT (BEP20)",
}

MANUAL_LABELS = {
    "wallet": "💰 Wallet",
    "binance": "🟡 Binance",
    "upi": "⚪ UPI",
}


def welcome_text(first_name: str | None = None) -> str:
    name = first_name or "friend"
    return (
        f"👋 Welcome, <b>{name}</b>!\n\n"
        f"🛍️ <b>{settings.STORE_NAME}</b>\n"
        f"Premium digital products with fast delivery.\n\n"
        f"✅ Automatic crypto confirmation\n"
        f"✅ Manual Wallet, Binance & UPI approval\n"
        f"✅ Instant delivery after approval\n"
        f"✅ Order history and support\n\n"
        f"Choose an option below 👇"
    )


def product_caption(product) -> str:
    return (
        f"🔥 <b>{product.name}</b>\n\n"
        f"📂 Category: <b>{product.category}</b>\n"
        f"⚡ Delivery: <b>Instant after confirmation</b>\n"
        f"🛡️ Support: <b>Available</b>\n"
        f"📦 Sold: <b>{product.sold_count or 0}</b>\n\n"
        f"{product.description}\n\n"
        f"━━━━━━━━━━━━━━\n"
        f"💵 Price: <b>${float(product.price):.2f}</b>\n"
        f"👇 Choose a payment method to continue."
    )


@router.message(CommandStart())
async def start(message: Message):
    async with SessionLocal() as session:
        await repo.upsert_user(session, message.from_user)

    text = welcome_text(message.from_user.first_name if message.from_user else None)
    if settings.WELCOME_IMAGE_FILE_ID:
        await message.answer_photo(settings.WELCOME_IMAGE_FILE_ID, caption=text, reply_markup=main_menu_kb(), parse_mode="HTML")
    else:
        await message.answer(text, reply_markup=main_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "home")
async def home(call: CallbackQuery):
    await call.message.answer(welcome_text(call.from_user.first_name), reply_markup=main_menu_kb(), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "shop")
async def shop(call: CallbackQuery):
    async with SessionLocal() as session:
        categories = await repo.list_categories(session)
    if not categories:
        await call.message.answer("No products are available yet.")
    else:
        await call.message.answer("📂 <b>Choose a category</b>", reply_markup=categories_kb(categories), parse_mode="HTML")
    await call.answer()


@router.message(Command("products"))
async def products_cmd(message: Message):
    async with SessionLocal() as session:
        products = await repo.list_products(session)
    if not products:
        await message.answer("No products are available yet.")
        return
    await message.answer("🔥 <b>Available Products</b>", reply_markup=product_list_kb(products), parse_mode="HTML")


@router.callback_query(F.data.startswith("cat:"))
async def category_products(call: CallbackQuery):
    category = call.data.split(":", 1)[1]
    async with SessionLocal() as session:
        if category == "__all__":
            products = await repo.list_products(session)
            title = "🔥 All Products"
        else:
            products = await repo.list_products_by_category(session, category)
            title = f"📂 {category}"
    if not products:
        await call.message.answer("No products in this category yet.")
    else:
        await call.message.answer(f"<b>{title}</b>", reply_markup=product_list_kb(products), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "reviews")
async def reviews(call: CallbackQuery):
    await call.message.answer(settings.REVIEWS_TEXT)
    await call.answer()


@router.callback_query(F.data == "myorders")
async def my_orders(call: CallbackQuery):
    async with SessionLocal() as session:
        orders = await repo.user_orders(session, call.from_user.id)
    if not orders:
        await call.message.answer("📦 You have no orders yet. Start shopping and your orders will appear here.")
    else:
        lines = ["📦 <b>My Recent Orders</b>"]
        for o in orders:
            lines.append(f"#{o.id} | Product {o.product_id} | {o.status} | ${float(o.amount):.2f}")
        await call.message.answer("\n".join(lines), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("product:"))
async def show_product(call: CallbackQuery):
    product_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
    if not product or not product.active:
        await call.answer("Product not found.", show_alert=True)
        return
    caption = product_caption(product)
    if product.image_file_id:
        await call.message.answer_photo(product.image_file_id, caption=caption, reply_markup=product_kb(product.id), parse_mode="HTML")
    else:
        await call.message.answer(caption, reply_markup=product_kb(product.id), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data.startswith("paymenu:"))
async def payment_menu(call: CallbackQuery):
    product_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
    if not product or not product.active:
        await call.answer("Product not found.", show_alert=True)
        return
    await call.message.answer(
        f"💳 <b>Choose Payment Method</b>\n\n"
        f"📦 Product: <b>{product.name}</b>\n"
        f"💵 Total: <b>${float(product.price):.2f}</b>\n\n"
        f"Select the method you prefer 👇",
        reply_markup=payment_methods_kb(product.id),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("manual:"))
async def manual_payment(call: CallbackQuery):
    _, product_id_raw, method = call.data.split(":")
    product_id = int(product_id_raw)

    # Validate the selected manual method before creating an order, so disabled
    # methods do not leave unusable pending orders in the database.
    if method == "wallet" and not settings.WALLET_ADDRESS:
        await call.message.answer("Wallet payment is not configured yet. Please choose another method.")
        await call.answer()
        return
    if method == "binance" and not settings.BINANCE_PAY_ID:
        await call.message.answer("Binance payment is not configured yet. Please choose another method.")
        await call.answer()
        return
    if method == "upi" and not settings.UPI_ID:
        await call.message.answer("UPI payment is not configured yet. Please choose another method.")
        await call.answer()
        return

    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        product = await repo.get_product(session, product_id)
        if not product or not product.active:
            await call.answer("Product not found.", show_alert=True)
            return
        order = await repo.create_order(session, call.from_user.id, product, settings.CURRENCY, method)

    label = MANUAL_LABELS[method]
    if method == "wallet":
        destination = f"Wallet address / ID:\n<code>{settings.WALLET_ADDRESS}</code>"
        amount_line = f"Amount: <b>${float(product.price):.2f}</b>"
    elif method == "binance":
        destination = f"Binance Pay ID:\n<code>{settings.BINANCE_PAY_ID}</code>"
        amount_line = f"Amount: <b>${float(product.price):.2f} USDT</b>"
    else:
        inr_amount = float(product.price) * float(settings.UPI_INR_PER_USD)
        destination = f"UPI ID:\n<code>{settings.UPI_ID}</code>\nName: <b>{settings.UPI_NAME}</b>"
        amount_line = f"Amount: <b>₹{inr_amount:.2f}</b>"

    await call.message.answer(
        f"{label}\n\n"
        f"🧾 Order ID: <code>{order.id}</code>\n"
        f"📦 Product: <b>{product.name}</b>\n"
        f"{amount_line}\n\n"
        f"{destination}\n\n"
        f"After paying, send the screenshot, transaction ID, UTR, or receipt here.\n"
        f"⚠️ Delivery happens only after admin confirms the money has arrived.",
        reply_markup=manual_payment_kb(order.id),
        parse_mode="HTML",
    )
    await call.answer()


@router.callback_query(F.data.startswith("proofhelp:"))
async def proof_help(call: CallbackQuery):
    order_id = call.data.split(":")[1]
    await call.answer()
    await call.message.answer(
        f"📤 Send payment proof for order <code>{order_id}</code> now.\n\n"
        "Accepted: screenshot, receipt document, UTR, or transaction ID.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("paycoin:"))
async def paycoin(call: CallbackQuery):
    _, product_id_raw, pay_currency = call.data.split(":")
    product_id = int(product_id_raw)
    async with SessionLocal() as session:
        await repo.upsert_user(session, call.from_user)
        product = await repo.get_product(session, product_id)
        if not product or not product.active:
            await call.answer("Product not found.", show_alert=True)
            return
        order = await repo.create_order(session, call.from_user.id, product, settings.CURRENCY, pay_currency)
        try:
            payment = await NowPayments().create_payment(
                order_id=order.id,
                price_amount=float(product.price),
                price_currency=settings.CURRENCY,
                pay_currency=pay_currency,
                description=product.name,
            )
        except Exception as exc:
            await call.message.answer(f"Payment setup error. Please contact support.\n\n{exc}")
            await call.answer()
            return

        payment_id = str(payment.get("payment_id") or payment.get("id") or "")
        pay_address = payment.get("pay_address") or ""
        pay_amount = payment.get("pay_amount") or ""
        network = payment.get("network") or ""
        payment_url = payment.get("payment_url") or payment.get("invoice_url") or None
        await repo.set_order_invoice(session, order.id, payment_id, payment_url or "")

    label = PAYMENT_LABELS.get(pay_currency, pay_currency.upper())
    text = (
        f"{label}\n\n"
        f"🧾 Order ID: <code>{order.id}</code>\n"
        f"📦 Product: <b>{product.name}</b>\n"
        f"💵 Price: <b>${float(product.price):.2f}</b>\n\n"
        f"Send exactly:\n<code>{pay_amount} {pay_currency.upper()}</code>\n\n"
        f"To this address:\n<code>{pay_address}</code>\n"
    )
    if network:
        text += f"\nNetwork: <b>{network}</b>\n"
    text += "\n⚠️ Send only the selected coin/network.\n✅ Delivery is automatic after provider confirmation."
    await call.message.answer(text, reply_markup=payment_info_kb(payment_url), parse_mode="HTML")
    await call.answer()


@router.callback_query(F.data == "paid:info")
async def paid_info(call: CallbackQuery):
    await call.answer("Payment is checked automatically. Delivery happens after provider confirmation.", show_alert=True)


async def _notify_admins(message: Message, order) -> None:
    username = f"@{message.from_user.username}" if message.from_user and message.from_user.username else "No username"
    summary = (
        f"🧾 <b>Payment proof submitted</b>\n\n"
        f"Order: <code>{order.id}</code>\n"
        f"Customer: <b>{message.from_user.full_name}</b> ({username})\n"
        f"Telegram ID: <code>{message.from_user.id}</code>\n"
        f"Product: <b>{order.product.name}</b>\n"
        f"Method: <b>{MANUAL_LABELS.get(order.payment_method, order.payment_method)}</b>\n"
        f"Amount: <b>${float(order.amount):.2f}</b>\n\n"
        f"Confirm the money in the real account before approval."
    )
    for admin_id in settings.admin_ids_set:
        try:
            if message.photo:
                await message.bot.send_photo(admin_id, message.photo[-1].file_id, caption=summary, reply_markup=admin_review_kb(order.id), parse_mode="HTML")
            elif message.document:
                await message.bot.send_document(admin_id, message.document.file_id, caption=summary, reply_markup=admin_review_kb(order.id), parse_mode="HTML")
            else:
                proof = message.text or ""
                await message.bot.send_message(admin_id, summary + f"\n\nProof / reference:\n<code>{proof}</code>", reply_markup=admin_review_kb(order.id), parse_mode="HTML")
        except Exception:
            continue


@router.message(F.photo | F.document | (F.text & ~F.text.startswith("/")))
async def payment_proof(message: Message):
    if not message.from_user:
        return
    async with SessionLocal() as session:
        order = await repo.latest_manual_order_waiting_for_proof(session, message.from_user.id)
        if not order:
            if message.document:
                await message.answer(f"📎 File received. Telegram file_id:\n<code>{message.document.file_id}</code>", parse_mode="HTML")
            return

        if message.photo:
            proof_type, proof_value = "photo", message.photo[-1].file_id
        elif message.document:
            proof_type, proof_value = "document", message.document.file_id
        else:
            proof_type, proof_value = "text", message.text or ""

        await repo.save_payment_proof(session, order, proof_type, proof_value)

    await _notify_admins(message, order)
    await message.answer(
        f"✅ Payment proof received for order <code>{order.id}</code>.\n\n"
        "The admin will verify the payment. After approval, your product will be delivered automatically.",
        parse_mode="HTML",
    )
