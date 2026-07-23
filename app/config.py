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
    REVIEWS_TEXT: str = "⭐ Trusted store\n✅ Instant delivery\n🛡 Friendly support"
    WELCOME_IMAGE_FILE_ID: str = ""
    TRC20_RECEIVE_ADDRESS: str = ""
    TRONGRID_API_KEY: str = ""
    TRC20_PAYMENT_TIMEOUT_MINUTES: int = 20
    TRC20_POLL_SECONDS: int = 15

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
        return {int(x) for x in self.ADMIN_IDS.replace(" ", "").split(",") if x}

    @property
    def webhook_url(self) -> str:
        return self.PUBLIC_URL.rstrip("/") + self.WEBHOOK_PATH

    @property
    def support_link(self) -> str | None:
        username = self.SUPPORT_USERNAME.strip().lstrip("@")
        return f"https://t.me/{username}" if username else None

settings = Settings()
