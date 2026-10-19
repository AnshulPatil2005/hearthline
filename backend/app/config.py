from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEV_SECRET = "dev-only-insecure-secret-change-me-0123456789"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    environment: str = "development"
    database_url: str | None = None
    # Signs login tokens, media links and PayPal sign-in state. Render generates a random value; the default is for
    # local development only, and production refuses to start with it.
    secret_key: str = DEV_SECRET
    token_ttl_hours: int = 72
    # Localhost on any port, plus the Render static site (and its preview environments).
    cors_origin_regex: str = r"http://localhost:\d+|https://hearthline-web(-[a-z0-9-]+)?\.onrender\.com"

    # LLM providers (OpenAI-compatible APIs). AI_MODELS is a `provider:model` fallback list, tried in order.
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ai_models: str = (
        "gemini:gemini-flash-lite-latest,gemini:gemma-4-31b-it,"
        "openrouter:google/gemma-4-31b-it:free,openrouter:openrouter/free"
    )

    channel3_api_key: str | None = None

    # Where the web app lives, for links the API hands out (PayPal return pages, registry links).
    # On Render, WEB_HOST is the static site's hostname (render.yaml) and RENDER_EXTERNAL_HOSTNAME is ours.
    web_host: str | None = None
    render_external_hostname: str | None = None

    paypal_client_id: str | None = None
    paypal_client_secret: str | None = None
    paypal_environment: str = "sandbox"
    paypal_webhook_id: str | None = None
    # Log in with PayPal sends people back here. PayPal only saves public https return URLs, so local development
    # registers a placeholder (e.g. https://example.com/connect/paypal); empty = the web app's /connect/paypal.
    paypal_connect_return_url: str | None = None
    # Sandbox test accounts used by spikes and demo seeding.
    paypal_sandbox_retailer_email: str | None = None
    paypal_sandbox_payout_receivers: str = ""

    @model_validator(mode="after")
    def _real_secret_in_production(self) -> "Settings":
        if self.environment == "production" and (self.secret_key == DEV_SECRET or len(self.secret_key) < 32):
            raise ValueError("Set SECRET_KEY to a long random value in production (render.yaml generates one)")
        return self

    @property
    def web_url(self) -> str:
        if not self.web_host:
            return "http://localhost:5173"
        # A Blueprint's `fromService ... host` is the service's name on Render's private network ("hearthline-web");
        # its public address is that name under onrender.com.
        return f"https://{self.web_host if '.' in self.web_host else self.web_host + '.onrender.com'}"

    @property
    def api_url(self) -> str:
        host = self.render_external_hostname
        return f"https://{host}" if host else "http://localhost:8000"

    @property
    def paypal_configured(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_client_secret)


@lru_cache
def get_settings() -> Settings:
    return Settings()
