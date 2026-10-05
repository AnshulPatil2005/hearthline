from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title="Phoenix API",
    version="0.1.0",
    description="Disaster recovery platform: Prepare, Respond, Rebuild, Reopen.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "environment": settings.environment,
        "integrations": {
            "Database": bool(settings.database_url),
            "Claude": bool(settings.anthropic_api_key),
            "Channel3": bool(settings.channel3_api_key),
            "PayPal": settings.paypal_configured,
        },
    }
