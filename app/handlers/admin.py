from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from app.db.session import SessionLocal
from app.db import repo
from app.services.delivery import deliver_order
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


def admin_only(message: Message) -> bool:
    return bool(message.from_user and is_admin(message.from_user.id))


@router.message(Command("admin"))
async def admin(message: Message):
    if not admin_only(message):
        return
    await message.answer(
        "👤 <b>Admin Panel</b>\n\n"
        "/addproduct - Add product\n"
        "/listproducts - List products\n"
        "/delproduct PRODUCT_ID - Disable product\n"
        "/orders - Recent orders\n"
        "/stats - Store stats\n\n"
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
            await repo.set_order_status(session, order, "delivery_failed")
            await call.message.answer(f"⚠️ Payment approved, but delivery failed for order #{order.id}:\n{exc}")
            await call.answer("Delivery failed. Check the message.", show_alert=True)
            return

    await call.message.edit_reply_markup(reply_markup=None)
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
    await state.set_state(AddProduct.category)
    await message.answer("Product category? Example: Courses, AI Tools, Streaming, Software")


@router.message(AddProduct.category)
async def add_category(message: Message, state: FSMContext):
    await state.update_data(category=message.text.strip())
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
    except ValueError:
        await message.answer("Please send a valid number, like 4.50")
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
    await message.answer(f"✅ Product added. ID: {product.id}")


@router.message(Command("listproducts"))
async def list_products(message: Message):
    if not admin_only(message):
        return
    async with SessionLocal() as session:
        products = await repo.list_products(session, only_active=False)
    if not products:
        await message.answer("No products yet.")
        return
    lines = ["📦 Products:"]
    for p in products:
        image = "🖼️" if p.image_file_id else "—"
        lines.append(f"#{p.id} | {'✅' if p.active else '❌'} | {image} | {p.category} | {p.name} | ${float(p.price):.2f}")
    await message.answer("\n".join(lines))


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
