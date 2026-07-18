from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db import repo
from app.db.session import SessionLocal
from app.services.delivery import deliver_order
from app.services.announcements import notify_restock
from app.utils.security import is_admin

router = Router()


class AddProduct(StatesGroup):
    category = State()
    name = State()
    price = State()
    description = State()
    image = State()
    delivery = State()
    is_file_id = State()


class EditProduct(StatesGroup):
    value = State()


class ManualDelivery(StatesGroup):
    content = State()


EDITABLE_FIELDS = {
    "name": "Name",
    "price": "Price",
    "category": "Category",
    "description": "Description",
    "image": "Image",
    "delivery": "Delivery content",
    "delivery_note": "Delivery note",
}


def admin_only(message: Message) -> bool:
    return bool(message.from_user and is_admin(message.from_user.id))


async def existing_categories() -> list[str]:
    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=False)
    return sorted({p.category.strip() for p in products if p.category and p.category.strip() and not p.category.strip().startswith("/")})


def category_choice_kb(categories: list[str], prefix: str) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📂 {category}", callback_data=f"{prefix}:{index}")] for index, category in enumerate(categories)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_product_kb(product_id: int, active: bool) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Name", callback_data=f"editproduct:{product_id}:name"),
                InlineKeyboardButton(text="💵 Price", callback_data=f"editproduct:{product_id}:price"),
            ],
            [
                InlineKeyboardButton(text="📂 Category", callback_data=f"editproduct:{product_id}:category"),
                InlineKeyboardButton(text="📄 Description", callback_data=f"editproduct:{product_id}:description"),
            ],
            [
                InlineKeyboardButton(text="🖼 Image", callback_data=f"editproduct:{product_id}:image"),
                InlineKeyboardButton(text="📦 Delivery", callback_data=f"editproduct:{product_id}:delivery"),
            ],
            [
                InlineKeyboardButton(text="📘 Delivery Note", callback_data=f"editproduct:{product_id}:delivery_note"),
            ],
            [
                InlineKeyboardButton(
                    text="🔴 Disable" if active else "🟢 Enable",
                    callback_data=f"toggleproduct:{product_id}",
                )
            ],
            [InlineKeyboardButton(text="✖ Close", callback_data="editproduct:close")],
        ]
    )


@router.message(Command("admin"))
async def admin(message: Message):
    if not admin_only(message):
        return
    await message.answer(
        "👤 <b>Admin Panel</b>\n\n"
        "/addproduct - Add product\n"
        "/listproducts - List products\n"
        "/editproduct PRODUCT_ID - Edit product\n"
        "/moveproduct PRODUCT_ID - Move product to category\n"
        "/deletecategory - Remove an empty category\n"
        "/delproduct PRODUCT_ID - Disable product\n"
        "/orders - Recent orders\n"
        "/stats - Store stats\n"
        "/addstock PRODUCT_ID - Add unique stock\n"
        "/stock PRODUCT_ID - Check available stock\n"
        "/removestock PRODUCT_ID QTY - Reduce stock\n"
        "/disablestock PRODUCT_ID - Use reusable delivery\n"
        "/editnote PRODUCT_ID - Set customer instructions\n"
        "/viewnote PRODUCT_ID - View customer instructions\n"
        "/announce MESSAGE - Post to Prime Hub update chats\n"
        "/replyticket ID MESSAGE - Reply to a ticket\n\n"
        "Manual payment proofs arrive here with Approve & Deliver / Reject buttons.",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("adminapprove:"))
async def approve_payment(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    order_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await call.answer("Order not found.", show_alert=True)
            return
        if order.delivered or order.status == "delivered":
            await call.answer("This order was already delivered.", show_alert=True)
            return
        if order.status != "proof_submitted":
            await call.answer(f"Order status is {order.status}; cannot approve.", show_alert=True)
            return
        await repo.set_order_status(session, order, "approved")
        try:
            await deliver_order(call.bot, session, order)
        except Exception as exc:
            message = str(exc)
            if "Not enough stock" in message:
                await repo.set_order_status(session, order, "paid_out_of_stock")
                try:
                    await call.bot.send_message(
                        order.user_id,
                        f"⚠️ Payment was confirmed for order #{order.id}, but the live stock sold out before confirmation. "
                        "Please contact support for a replacement or refund."
                    )
                except Exception:
                    pass
                await call.message.answer(
                    f"⚠️ Order #{order.id} is paid but live stock is unavailable. Arrange a replacement or refund."
                )
                await call.answer("Paid, but out of stock.", show_alert=True)
            else:
                await repo.set_order_status(session, order, "delivery_failed")
                await call.message.answer(f"⚠️ Payment approved, but delivery failed for order #{order.id}:\n{exc}")
                await call.answer("Delivery failed. Check the message.", show_alert=True)
            return

    await call.message.edit_reply_markup(reply_markup=None)
    if getattr(order.product, "delivery_mode", "instant") == "manual":
        await call.message.answer(f"✅ Order #{order_id} approved. Waiting for manual delivery; use /deliverorder {order_id}.")
        await call.answer("Approved; manual delivery pending.")
    else:
        await call.message.answer(f"✅ Order #{order_id} approved and delivered.")
        await call.answer("Approved and delivered.")


@router.callback_query(F.data.startswith("adminreject:"))
async def reject_payment(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    order_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        order = await repo.get_order_with_product(session, order_id)
        if not order:
            await call.answer("Order not found.", show_alert=True)
            return
        if order.delivered:
            await call.answer("Delivered orders cannot be rejected.", show_alert=True)
            return
        await repo.set_order_status(session, order, "rejected")
        try:
            await call.bot.send_message(
                order.user_id,
                f"❌ Payment proof for order <code>{order.id}</code> was rejected.\n\n"
                "Please check the amount/reference and contact support or create a new order.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"❌ Order #{order_id} rejected.")
    await call.answer("Rejected.")


@router.message(Command("addproduct"))
async def add_product(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    categories = await existing_categories()
    if not categories:
        await state.set_state(AddProduct.category)
        await message.answer("No existing categories found. Type the category name.")
        return
    await state.update_data(category_options=categories)
    await state.set_state(AddProduct.category)
    await message.answer(
        "📂 Choose the product category:",
        reply_markup=category_choice_kb(categories, "addcat"),
    )


@router.callback_query(AddProduct.category, F.data.startswith("addcat:"))
async def add_category_choice(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    data = await state.get_data()
    categories = data.get("category_options", [])
    try:
        category = categories[int(call.data.split(":")[1])]
    except (IndexError, ValueError):
        await call.answer("Category not found.", show_alert=True)
        return
    await state.update_data(category=category)
    await state.set_state(AddProduct.name)
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"✅ Category: {category}\n\nProduct name? Example: Coursera Premium 12M")
    await call.answer()


@router.message(AddProduct.category)
async def add_category(message: Message, state: FSMContext):
    # Fallback only when the store has no categories yet.
    category = (message.text or "").strip()
    if not category or category.startswith("/"):
        await message.answer("Please type a valid category name without a slash.")
        return
    await state.update_data(category=category)
    await state.set_state(AddProduct.name)
    await message.answer("Product name? Example: Coursera Premium 12M")


@router.message(AddProduct.name)
async def add_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(AddProduct.price)
    await message.answer("Price in USD? Example: 4.50")


@router.message(AddProduct.price)
async def add_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.strip())
        if price <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer("Please send a valid positive number, like 4.50")
        return
    await state.update_data(price=price)
    await state.set_state(AddProduct.description)
    await message.answer("Product description? Make it attractive.")


@router.message(AddProduct.description)
async def add_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text.strip())
    await state.set_state(AddProduct.image)
    await message.answer("Send product image/photo now, or type `skip`.", parse_mode="Markdown")


@router.message(AddProduct.image)
async def add_image(message: Message, state: FSMContext):
    image_file_id = None
    if message.photo:
        image_file_id = message.photo[-1].file_id
    elif message.text and message.text.strip().lower() == "skip":
        image_file_id = None
    else:
        await message.answer("Please send a photo, or type `skip`.")
        return
    await state.update_data(image_file_id=image_file_id)
    await state.set_state(AddProduct.delivery)
    await message.answer("Delivery content? Paste account/key/link/text to send after payment.")


@router.message(AddProduct.delivery)
async def add_delivery(message: Message, state: FSMContext):
    await state.update_data(delivery=message.text.strip())
    await state.set_state(AddProduct.is_file_id)
    await message.answer("Is this delivery a Telegram file_id? Reply yes or no.")


@router.message(AddProduct.is_file_id)
async def add_is_file(message: Message, state: FSMContext):
    answer = message.text.strip().lower()
    is_file_id = answer in {"yes", "y", "true", "1"}
    data = await state.get_data()
    async with SessionLocal() as session:
        product = await repo.create_product(
            session=session,
            category=data["category"],
            name=data["name"],
            price=data["price"],
            description=data["description"],
            delivery=data["delivery"],
            is_file_id=is_file_id,
            image_file_id=data.get("image_file_id"),
        )
    await state.clear()
    await message.answer(f"✅ Product added. ID: {product.id}\n\n⚠️ Stock is 0, so customers cannot order yet. Add stock with /addstock {product.id}")


@router.message(Command("listproducts"))
async def list_products(message: Message):
    if not admin_only(message):
        return
    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=False)
        stock_counts = {p.id: await repo.available_stock_count(session, p.id) for p in products}
    if not products:
        await message.answer("No products yet.")
        return
    lines = ["📦 Products:"]
    for p in products:
        image = "🖼️" if p.image_file_id else "—"
        stock = f"stock {stock_counts[p.id]}" if p.stock_enabled else "reusable"
        lines.append(f"#{p.id} | {'✅' if p.active else '❌'} | {image} | {p.category} | {p.name} | ${float(p.price):.2f} | {stock}")
    lines.append("\nEdit with: /editproduct PRODUCT_ID")
    await message.answer("\n".join(lines))


@router.message(Command("moveproduct"))
async def move_product_command(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /moveproduct PRODUCT_ID\nExample: /moveproduct 12")
        return
    product_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
    if not product:
        await message.answer("Product not found.")
        return
    categories = await existing_categories()
    categories = [c for c in categories if c != product.category]
    if not categories:
        await message.answer("No other category is available.")
        return
    await state.update_data(move_product_id=product_id, move_category_options=categories)
    await message.answer(
        f"📦 <b>{product.name}</b>\nCurrent category: {product.category}\n\nChoose the new category:",
        reply_markup=category_choice_kb(categories, "movecat"),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("movecat:"))
async def move_product_category(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    data = await state.get_data()
    categories = data.get("move_category_options", [])
    product_id = data.get("move_product_id")
    try:
        category = categories[int(call.data.split(":")[1])]
    except (IndexError, ValueError):
        await call.answer("Category not found.", show_alert=True)
        return
    if not product_id:
        await call.answer("Move session expired. Run /moveproduct again.", show_alert=True)
        return
    async with SessionLocal() as session:
        product = await repo.update_product_field(session, int(product_id), "category", category)
    await state.clear()
    if not product:
        await call.answer("Product not found.", show_alert=True)
        return
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(f"✅ <b>{product.name}</b> moved to <b>{category}</b>.", parse_mode="HTML")
    await call.answer("Product moved.")


@router.message(Command("deletecategory"))
async def delete_category_command(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    categories = await existing_categories()
    if not categories:
        await message.answer("No categories found.")
        return
    await state.update_data(delete_category_options=categories)
    await message.answer(
        "🗑 Choose a category to remove.\n\nOnly an empty category can be removed safely.",
        reply_markup=category_choice_kb(categories, "delcat"),
    )


@router.callback_query(F.data.startswith("delcat:"))
async def delete_category_choice(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    data = await state.get_data()
    categories = data.get("delete_category_options", [])
    try:
        category = categories[int(call.data.split(":")[1])]
    except (IndexError, ValueError):
        await call.answer("Category not found.", show_alert=True)
        return
    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=False)
        assigned = [p for p in products if p.category == category]
    if assigned:
        await call.answer(
            f"{len(assigned)} product(s) still use this category. Move them first.",
            show_alert=True,
        )
        return
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.message.answer(
        f"✅ Category <b>{category}</b> removed from the menu.\n"
        "Categories are generated from product category values, so an empty category disappears automatically.",
        parse_mode="HTML",
    )
    await call.answer("Category removed.")


@router.message(Command("editproduct"))
async def edit_product(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /editproduct PRODUCT_ID\nExample: /editproduct 1")
        return

    product_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)

    if not product:
        await message.answer("Product not found.")
        return

    await message.answer(
        f"✏️ <b>Edit Product #{product.id}</b>\n\n"
        f"Name: {product.name}\n"
        f"Price: ${float(product.price):.2f}\n"
        f"Category: {product.category}\n"
        f"Status: {'Active' if product.active else 'Disabled'}\n\n"
        "Choose what to edit:",
        reply_markup=edit_product_kb(product.id, product.active),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "editproduct:close")
async def close_edit_product(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=None)
    await call.answer("Closed.")


@router.callback_query(F.data.startswith("editproduct:"))
async def choose_edit_field(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return

    parts = call.data.split(":")
    if len(parts) != 3:
        return
    product_id = int(parts[1])
    field = parts[2]
    if field not in EDITABLE_FIELDS:
        await call.answer("Unknown field.", show_alert=True)
        return

    await state.update_data(product_id=product_id, field=field)
    await state.set_state(EditProduct.value)

    if field == "image":
        prompt = "Send the new product photo, or type `remove` to delete the current image."
    elif field == "price":
        prompt = "Send the new price as a positive number, for example: 10.00"
    elif field == "delivery_note":
        prompt = (
            "Send the customer instructions for this product.\n\n"
            "You may use: {product_name}, {quantity}, {order_id}, {support_username}.\n"
            "Type `remove` to clear the note."
        )
    else:
        prompt = f"Send the new {EDITABLE_FIELDS[field].lower()}."

    await call.message.answer(prompt, parse_mode="Markdown")
    await call.answer()


@router.message(EditProduct.value)
async def save_edited_value(message: Message, state: FSMContext):
    if not admin_only(message):
        await state.clear()
        return

    data = await state.get_data()
    product_id = int(data["product_id"])
    field = data["field"]

    if field == "image":
        if message.photo:
            value = message.photo[-1].file_id
        elif message.text and message.text.strip().lower() == "remove":
            value = None
        else:
            await message.answer("Send a photo, or type `remove`.")
            return
    else:
        if not message.text:
            await message.answer("Please send text.")
            return
        value = message.text.strip()
        if field == "delivery_note" and value.lower() == "remove":
            value = ""
        if field == "price":
            try:
                value = float(value)
                if value <= 0:
                    raise ValueError
            except ValueError:
                await message.answer("Please send a valid positive number, for example: 10.00")
                return

    async with SessionLocal() as session:
        product = await repo.update_product_field(session, product_id, field, value)

    await state.clear()
    if not product:
        await message.answer("Product not found.")
        return

    display_value = f"${float(product.price):.2f}" if field == "price" else ("updated" if field == "image" else str(value))
    await message.answer(
        f"✅ {EDITABLE_FIELDS[field]} updated to: {display_value}\n\n"
        f"Use /editproduct {product_id} to edit another field."
    )


@router.callback_query(F.data.startswith("toggleproduct:"))
async def toggle_product(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Not authorized.", show_alert=True)
        return
    product_id = int(call.data.split(":")[1])
    async with SessionLocal() as session:
        product = await repo.toggle_product_active(session, product_id)
    if not product:
        await call.answer("Product not found.", show_alert=True)
        return
    await call.message.edit_reply_markup(reply_markup=edit_product_kb(product.id, product.active))
    await call.answer("Product enabled." if product.active else "Product disabled.")


@router.message(Command("delproduct"))
async def del_product(message: Message):
    if not admin_only(message):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /delproduct PRODUCT_ID")
        return
    async with SessionLocal() as session:
        ok = await repo.deactivate_product(session, int(parts[1]))
    await message.answer("✅ Disabled." if ok else "Product not found.")


@router.message(Command("orders"))
async def orders(message: Message):
    if not admin_only(message):
        return
    async with SessionLocal() as session:
        orders = await repo.recent_orders(session)
    if not orders:
        await message.answer("No orders yet.")
        return
    lines = ["🧾 Recent orders:"]
    for o in orders:
        lines.append(f"#{o.id} | user {o.user_id} | product {o.product_id} | {o.payment_method} | {o.status} | ${float(o.amount):.2f}")
    await message.answer("\n".join(lines))


@router.message(Command("stats"))
async def stats_cmd(message: Message):
    if not admin_only(message):
        return
    async with SessionLocal() as session:
        users, orders_count, revenue = await repo.stats(session)
    await message.answer(f"📊 Stats\nUsers: {users}\nOrders: {orders_count}\nRevenue: ${revenue:.2f}")


@router.message(Command("editnote"))
async def edit_note_command(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /editnote PRODUCT_ID\nExample: /editnote 1")
        return
    product_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
    if not product:
        await message.answer("Product not found.")
        return
    await state.update_data(product_id=product_id, field="delivery_note")
    await state.set_state(EditProduct.value)
    await message.answer(
        f"📘 Send the delivery instructions for <b>{product.name}</b>.\n\n"
        "Example:\n"
        "• Login at https://example.com\n"
        "• Do not change the recovery email\n"
        "• Replacement support: 24 hours\n\n"
        "Available placeholders: <code>{product_name}</code>, <code>{quantity}</code>, "
        "<code>{order_id}</code>, <code>{support_username}</code>.\n"
        "Type <code>remove</code> to clear the note.",
        parse_mode="HTML",
    )


@router.message(Command("viewnote"))
async def view_note_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /viewnote PRODUCT_ID\nExample: /viewnote 1")
        return
    product_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
    if not product:
        await message.answer("Product not found.")
        return
    note = product.delivery_note or "No delivery note is configured."
    await message.answer(
        f"📘 <b>Delivery note for {product.name}</b>\n\n<pre>{note}</pre>",
        parse_mode="HTML",
    )


class AddStock(StatesGroup):
    items = State()


@router.message(Command("addstock"))
async def add_stock_command(message: Message, state: FSMContext):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /addstock PRODUCT_ID\nExample: /addstock 1")
        return
    product_id = int(parts[1])
    async with SessionLocal() as session:
        product = await repo.get_product(session, product_id)
    if not product:
        await message.answer("Product not found.")
        return
    await state.update_data(stock_product_id=product_id)
    await state.set_state(AddStock.items)
    await message.answer(
        f"📦 Add stock for <b>{product.name}</b>\n\n"
        "Paste one account/key/item per line.\n\n"
        "Example:\n<code>email1@example.com:password1\nemail2@example.com:password2</code>",
        parse_mode="HTML",
    )


@router.message(AddStock.items)
async def receive_stock_items(message: Message, state: FSMContext):
    if not admin_only(message):
        await state.clear()
        return
    if not message.text:
        await message.answer("Send stock as text, one item per line.")
        return
    data = await state.get_data()
    product_id = int(data["stock_product_id"])
    items = [line.strip() for line in message.text.splitlines() if line.strip()]
    async with SessionLocal() as session:
        added = await repo.add_stock_items(session, product_id, items)
        total = await repo.available_stock_count(session, product_id)
        product = await repo.get_product(session, product_id)
    await state.clear()
    await message.answer(f"✅ Added {added} stock item(s).\n📦 Available stock now: {total}")
    if product and added > 0:
        users_notified, chats_notified = await notify_restock(
            message.bot, product, added, total
        )
        await message.answer(
            f"🔔 Restock notifications sent to {users_notified} subscriber(s) "
            f"and {chats_notified} update chat(s)."
        )


@router.message(Command("stock"))
async def stock_status(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    async with SessionLocal() as session:
        if len(parts) == 1:
            rows = await repo.all_product_stock(session)
            if not rows:
                await message.answer("No products found.")
                return
            lines = ["📦 <b>All Product Stock</b>"]
            for product, available, reserved in rows:
                mode = getattr(product, "delivery_mode", "instant")
                status = "✅" if available > 0 else "❌"
                lines.append(f"{status} #{product.id} {product.name} | ${float(product.price):.2f} | Available: {available} | {mode}")
            await message.answer("\n".join(lines), parse_mode="HTML")
            return
        if len(parts) != 2 or not parts[1].isdigit():
            await message.answer("Usage: /stock or /stock PRODUCT_ID")
            return
        product_id = int(parts[1])
        product = await repo.get_product(session, product_id)
        if not product:
            await message.answer("Product not found.")
            return
        available = await repo.available_stock_count(session, product_id)
    await message.answer(f"📦 <b>{product.name}</b>\nPrice: <b>${float(product.price):.2f}</b>\nAvailable stock: <b>{available}</b>\nDelivery: <b>{getattr(product, 'delivery_mode', 'instant')}</b>", parse_mode="HTML")


@router.message(Command("deliverymode"))
async def delivery_mode_command(message: Message):
    if not admin_only(message): return
    parts=(message.text or "").split()
    if len(parts)!=3 or not parts[1].isdigit() or parts[2].lower() not in {"instant","manual"}:
        await message.answer("Usage: /deliverymode PRODUCT_ID instant|manual")
        return
    async with SessionLocal() as session:
        product=await repo.set_delivery_mode(session,int(parts[1]),parts[2].lower())
    await message.answer(f"✅ Delivery mode set to {parts[2].lower()}" if product else "Product not found.")


@router.message(Command("setmanualstock"))
async def set_manual_stock(message: Message):
    if not admin_only(message): return
    parts=(message.text or "").split()
    if len(parts)!=3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Usage: /setmanualstock PRODUCT_ID QTY")
        return
    async with SessionLocal() as session:
        product=await repo.set_delivery_mode(session,int(parts[1]),"manual")
        if not product:
            await message.answer("Product not found."); return
        added=await repo.add_manual_stock_slots(session,int(parts[1]),int(parts[2]))
        total=await repo.available_stock_count(session,int(parts[1]))
    await message.answer(f"✅ Added {added} manual-delivery unit(s). Available: {total}")


@router.message(Command("deliverorder"))
async def deliver_order_command(message: Message, state: FSMContext):
    if not admin_only(message): return
    parts=(message.text or "").split()
    if len(parts)!=2 or not parts[1].isdigit():
        await message.answer("Usage: /deliverorder ORDER_ID")
        return
    async with SessionLocal() as session:
        order=await repo.get_order_with_product(session,int(parts[1]))
        if not order or order.status != "paid_manual":
            await message.answer("Order not found or not waiting for manual delivery."); return
    await state.update_data(manual_order_id=int(parts[1]))
    await state.set_state(ManualDelivery.content)
    await message.answer("Send the manual delivery content now (text, photo, or document).")


@router.message(ManualDelivery.content)
async def send_manual_delivery(message: Message, state: FSMContext):
    if not admin_only(message): await state.clear(); return
    data=await state.get_data(); order_id=int(data["manual_order_id"])
    async with SessionLocal() as session:
        order=await repo.get_order_with_product(session,order_id)
        if not order or order.status != "paid_manual":
            await message.answer("Order is no longer waiting for manual delivery."); await state.clear(); return
        if message.photo:
            await message.bot.send_photo(order.user_id,message.photo[-1].file_id,caption=f"✅ Manual delivery for order #{order.id}")
        elif message.document:
            await message.bot.send_document(order.user_id,message.document.file_id,caption=f"✅ Manual delivery for order #{order.id}")
        elif message.text:
            await message.bot.send_message(order.user_id,f"✅ <b>Order #{order.id} delivered</b>\n\n{message.text}",parse_mode="HTML")
        else:
            await message.answer("Send text, photo, or document."); return
        await repo.mark_delivered(session,order)
    await state.clear(); await message.answer(f"✅ Order #{order_id} manually delivered.")


@router.message(Command("removestock"))
async def remove_stock_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Usage: /removestock PRODUCT_ID QUANTITY\nExample: /removestock 1 5")
        return
    product_id, quantity = int(parts[1]), int(parts[2])
    async with SessionLocal() as session:
        removed = await repo.remove_available_stock(session, product_id, quantity)
        remaining = await repo.available_stock_count(session, product_id)
    await message.answer(f"✅ Removed {removed} item(s).\n📦 Remaining stock: {remaining}")


@router.message(Command("disablestock"))
async def disable_stock_command(message: Message):
    if not admin_only(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Usage: /disablestock PRODUCT_ID")
        return
    async with SessionLocal() as session:
        ok = await repo.disable_stock_mode(session, int(parts[1]))
    await message.answer("✅ Stock mode disabled; reusable delivery content will be used." if ok else "Product not found.")
