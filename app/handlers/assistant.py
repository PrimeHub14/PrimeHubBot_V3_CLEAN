from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import settings
from app.services.assistant import ask_store_assistant

router = Router()


class AssistantFlow(StatesGroup):
    question = State()


async def _start(message: Message, state: FSMContext) -> None:
    await state.clear()
    if not settings.OPENAI_API_KEY:
        await message.answer(
            "🤖 The AI assistant is not configured yet. Please use /help to open a support ticket."
        )
        return
    await state.set_state(AssistantFlow.question)
    await message.answer(
        "🤖 <b>Prime Hub Assistant</b>\n\n"
        "Ask a question about products, payments, wallet top-ups, orders, stock alerts, or delivery.\n\n"
        "Do not send passwords, OTPs, private keys, seed phrases, or payment secrets.",
        parse_mode="HTML",
    )


@router.message(Command("assistant"))
async def assistant_command(message: Message, state: FSMContext):
    await _start(message, state)


@router.callback_query(F.data == "assistant:start")
async def assistant_callback(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await _start(call.message, state)


@router.message(AssistantFlow.question)
async def assistant_question(message: Message, state: FSMContext):
    if not message.text:
        await message.answer("Please send your question as text.")
        return
    await message.bot.send_chat_action(message.chat.id, "typing")
    try:
        answer = await ask_store_assistant(message.text)
    except Exception:
        await state.clear()
        await message.answer(
            "⚠️ The AI assistant is unavailable right now. Please use /help to open a support ticket."
        )
        return
    await state.clear()
    await message.answer(f"🤖 <b>Prime Hub Assistant</b>\n\n{escape(answer)}", parse_mode="HTML")
