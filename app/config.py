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
    STORE_NAME: str = "PrimeHub Store"
    CURRENCY: str = "usd"
    SUPPORT_USERNAME: str = ""
    REVIEWS_TEXT: str = "⭐ 4.9/5 Customer Rating\n✅ Instant delivery\n🛡 Friendly replacement support\n💬 Fast support"
    WELCOME_IMAGE_FILE_ID: str = ""

    # Manual payment destinations
    WALLET_ADDRESS: str = ""
    BINANCE_PAY_ID: str = ""
    UPI_ID: str = ""
    UPI_NAME: str = "Prime Hub"
    UPI_INR_PER_USD: float = 86.5

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
    def webhook_url(self) -> str:
        return self.PUBLIC_URL.rstrip("/") + self.WEBHOOK_PATH

    @property
    def support_link(self) -> str | None:
        username = self.SUPPORT_USERNAME.strip().lstrip("@")
        return f"https://t.me/{username}" if username else None


settings = Settings()
