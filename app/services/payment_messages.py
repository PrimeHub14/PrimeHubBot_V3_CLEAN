async def remove_previous_payment_message(bot, order) -> None:
    """Remove the previous QR/payment card when the user switches method."""
    chat_id = getattr(order, "payment_message_chat_id", None)
    message_id = getattr(order, "payment_message_id", None)
    if chat_id and message_id:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
