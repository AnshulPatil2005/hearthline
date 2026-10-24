from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app import ai, mcp_server, store_mcp
from app.api import (
    alerts,
    auth,
    books,
    bryntum,
    claims,
    command,
    crews,
    disasters,
    disputes,
    households,
    impact,
    insurance,
    inventory,
    ledger,
    local_shop,
    mandates,
    navigator,
    paypal_connect,
    price_watch,
    public,
    purchases,
    rapid_aid,
    readiness,
    rebuild,
    registry,
    reopen,
    review,
    trust,
    webhooks,
)
from app.config import get_settings
from app.db import engine
from app.paypal import reporting

settings = get_settings()
mcp_app = mcp_server.http_app()
stores_mcp_app = store_mcp.http_app()  # local stores' pricing agents, for the Shopper


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with (
        mcp_app.router.lifespan_context(mcp_app),  # the MCP session managers run with the API
        stores_mcp_app.router.lifespan_context(stores_mcp_app),
    ):
        yield
    reporting.close()  # the PayPal SDK client's connection pool


app = FastAPI(
    title="Hearthline API",
    version="1.0.0",
    description=(
        "Disaster recovery platform: Prepare, Respond, Rebuild, Reopen. The **Public API v1** (`/v1`) is for "
        "partners, donors' apps and AI agents; the same operations are MCP tools at `/mcp`. Preparing a gift "
        "returns a PayPal approval link: a person approves every payment."
    ),
    lifespan=lifespan,
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
app.include_router(impact.router)
app.include_router(insurance.router)
app.include_router(disputes.router)
app.include_router(disputes.paypal_router)
app.include_router(paypal_connect.router)
app.include_router(books.router)
app.include_router(claims.router)
app.include_router(local_shop.router)
app.include_router(mandates.router)
app.include_router(navigator.router)
app.include_router(rapid_aid.router)
app.include_router(readiness.router)
app.include_router(disasters.router)
app.include_router(webhooks.router)
app.include_router(public.router)


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


# The store agents answer at /stores/mcp (Hearthline's Shopper only).
app.mount("/stores", stores_mcp_app)
# Last, so every API route above matches first: the MCP server answers at /mcp.
app.mount("/", mcp_app)
