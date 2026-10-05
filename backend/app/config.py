from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    environment: str = "development"
    database_url: str | None = None
    redis_url: str = "redis://localhost:6379"
    # Localhost on any port, plus the Render static site (and its preview environments).
    cors_origin_regex: str = r"http://localhost:\d+|https://phoenix-web(-[a-z0-9-]+)?\.onrender\.com"

    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5"

    channel3_api_key: str | None = None

    paypal_client_id: str | None = None
    paypal_client_secret: str | None = None
    paypal_environment: str = "sandbox"
    paypal_webhook_id: str | None = None
    # Sandbox test accounts used by spikes and demo seeding.
    paypal_sandbox_retailer_email: str | None = None
    paypal_sandbox_payout_receivers: str = ""

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
