from pydantic_settings import BaseSettings
from pydantic import field_validator


class Settings(BaseSettings):
    BOT_TOKEN: str
    ADMIN_IDS: str = ""
    DATABASE_URL: str
    PUBLIC_URL: str = ""
    WEBHOOK_PATH: str = "/nowpayments-webhook"
    NOWPAYMENTS_API_KEY: str = ""
    NOWPAYMENTS_IPN_SECRET: str = ""
    STORE_NAME: str = "Prime Hub Store"
    CURRENCY: str = "usd"
    SUPPORT_USERNAME: str = ""
    REVIEWS_TEXT: str = "⭐ 4.9/5 Customer Rating\n✅ Instant delivery\n🛡 Friendly replacement support\n💬 Fast support"
    WELCOME_IMAGE_FILE_ID: str = ""

    # Community updates and optional AI assistant
    UPDATE_CHAT_IDS: str = ""
    COMMUNITY_LINK: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-5-mini"

    # Manual payment destinations
    WALLET_ADDRESS: str = ""
    BINANCE_PAY_ID: str = ""
    UPI_ID: str = ""
    UPI_NAME: str = "Prime Hub"
    UPI_INR_PER_USD: float = 86.5

    # Direct USDT TRC20 payment verification
    TRC20_RECEIVE_ADDRESS: str = ""
    TRONGRID_API_KEY: str = ""
    TRC20_PAYMENT_TIMEOUT_MINUTES: int = 10
    TRC20_POLL_SECONDS: int = 15

    # Direct USDT BEP20 payment verification on BNB Smart Chain
    BEP20_RECEIVE_ADDRESS: str = ""
    BSC_RPC_URL: str = ""
    BEP20_PAYMENT_TIMEOUT_MINUTES: int = 30
    BEP20_POLL_SECONDS: int = 10
    BEP20_CONFIRMATIONS: int = 3
    BEP20_BACKFILL_BLOCKS: int = 10000

    @field_validator("DATABASE_URL")
    @classmethod
    def normalize_db_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def admin_ids_set(self) -> set[int]:
        ids: set[int] = set()
        for part in self.ADMIN_IDS.replace(" ", "").split(","):
            if part:
                ids.add(int(part))
        return ids

    @property
    def admin_ids(self) -> list[int]:
        # Compatibility alias used by the delivery service.
        return sorted(self.admin_ids_set)

    @property
    def webhook_url(self) -> str:
        return self.PUBLIC_URL.rstrip("/") + self.WEBHOOK_PATH

    @property
    def update_chat_ids(self) -> list[int | str]:
        values: list[int | str] = []
        for raw in self.UPDATE_CHAT_IDS.split(","):
            value = raw.strip()
            if not value:
                continue
            if value.lstrip("-").isdigit():
                values.append(int(value))
            else:
                values.append(value if value.startswith("@") else f"@{value}")
        return values

    @property
    def community_link(self) -> str | None:
        value = self.COMMUNITY_LINK.strip()
        if not value:
            return None
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return f"https://t.me/{value.lstrip('@')}"

    @property
    def support_link(self) -> str | None:
        username = self.SUPPORT_USERNAME.strip().lstrip("@")
        return f"https://t.me/{username}" if username else None


settings = Settings()
