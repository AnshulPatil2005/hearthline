from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import ai
from app.api import (
    alerts,
    auth,
    bryntum,
    command,
    crews,
    households,
    inventory,
    ledger,
    price_watch,
    purchases,
    rebuild,
    registry,
    reopen,
    review,
    trust,
    webhooks,
)
from app.config import get_settings
from app.db import engine

settings = get_settings()

app = FastAPI(
    title="Hearthline API",
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
app.include_router(auth.router)
app.include_router(households.router)
app.include_router(inventory.router)
app.include_router(alerts.router)
app.include_router(registry.router)
app.include_router(purchases.router)
app.include_router(ledger.router)
app.include_router(trust.router)
app.include_router(review.router)
app.include_router(bryntum.router)
app.include_router(rebuild.router)
app.include_router(command.router)
app.include_router(crews.router)
app.include_router(reopen.router)
app.include_router(price_watch.router)
app.include_router(webhooks.router)


def database_ok() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except SQLAlchemyError:
        return False


@app.get("/health", tags=["system"])
def health() -> dict:
    return {
        "status": "ok",
        "environment": settings.environment,
        "integrations": {
            "Database": database_ok(),
            "AI": ai.configured(),
            "Channel3": bool(settings.channel3_api_key),
            "PayPal": settings.paypal_configured,
        },
    }
