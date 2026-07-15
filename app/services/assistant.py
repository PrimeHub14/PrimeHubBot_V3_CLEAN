import aiohttp

from app.config import settings


STORE_INSTRUCTIONS = """You are the Prime Hub store assistant.
Answer only about using the Prime Hub Telegram store: browsing products, wallet top-ups,
order status, payment choices, stock alerts, delivery instructions, and support.
Never claim a payment is confirmed. Never request passwords, seed phrases, OTPs,
private keys, full card details, or API secrets. For account-specific or unresolved
issues, tell the customer to open a support ticket. Keep replies short and clear.
"""


async def ask_store_assistant(question: str) -> str:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("AI assistant is not configured")

    payload = {
        "model": settings.OPENAI_MODEL,
        "instructions": STORE_INSTRUCTIONS,
        "input": question[:3000],
        "max_output_tokens": 350,
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://api.openai.com/v1/responses",
            json=payload,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=45),
        ) as response:
            data = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"AI service error: {data}")

    if isinstance(data, dict) and data.get("output_text"):
        return str(data["output_text"]).strip()

    chunks: list[str] = []
    for item in data.get("output", []) if isinstance(data, dict) else []:
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                chunks.append(str(content["text"]))
    answer = "\n".join(chunks).strip()
    if not answer:
        raise RuntimeError("AI assistant returned no text")
    return answer
