"""Local stores' pricing agents, as an MCP server: the agent-to-agent side of the marketplace.

Hearthline's Shopper is the client. It asks a store's agent for a quote, may counter once, and accepts or declines.
Hearthline hosts an agent for each open, verified store, bound by the owner's rules (`app.market`,
`app.agents.store`); a store could run its own agent behind the same tools. Served over Streamable HTTP at
/stores/mcp to callers with Hearthline's internal token only: quotes reserve stock, so the public can't call them.
"""

import hashlib
import hmac
from decimal import Decimal

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app import market
from app.config import get_settings
from app.db import SessionLocal
from app.models import LocalOffer, MarketQuote

INSTRUCTIONS = """You are talking to the pricing agents of local stores in a disaster-hit town, each acting for its
store within the owner's rules. Ask a store for a quote on one of its catalog items, counter once if you need a lower
price, then accept or decline. Prices are per unit in US dollars. Accepting reserves the stock; payment follows
separately through PayPal."""

server = MCPServer(
    name="hearthline-stores",
    title="Hearthline local stores",
    description="Pricing agents of verified local stores that are open again after a disaster.",
    instructions=INSTRUCTIONS,
    version="1.0.0",
)


class Offer(BaseModel):
    offer_id: int
    title: str
    category: str
    list_price: str
    in_stock: int


class Quote(BaseModel):
    quote_id: int
    store: str
    offer_id: int
    offer: str
    quantity: int
    unit_price: str
    list_price: str
    total: str
    delivery_days: int
    status: (
        str  # quoted | countered (the store accepted the counter) | final (the store's lowest) | accepted | declined
    )
    message: str  # the store's latest words


def _quote(q: MarketQuote) -> Quote:
    return Quote(
        quote_id=q.id,
        store=q.business.name,
        offer_id=q.offer_id,
        offer=q.offer.title,
        quantity=q.quantity,
        unit_price=str(q.unit_price),
        list_price=str(q.list_price),
        total=str(q.unit_price * q.quantity),
        delivery_days=q.delivery_days,
        status=q.status,
        message=q.messages[-1]["text"] if q.messages else "",
    )


def _offer(o: LocalOffer) -> Offer:
    return Offer(offer_id=o.id, title=o.title, category=o.category, list_price=str(o.unit_price), in_stock=o.stock)


@server.tool(title="See a store's catalog")
def catalog(store: str) -> list[Offer]:
    """What a store sells and how many it has. `store` is the store's slug, e.g. "sablewood-mercantile"."""
    with SessionLocal() as db:
        return [_offer(o) for o in market.catalog(db, store)]


@server.tool(title="Ask a store for a quote")
def request_quote(
    store: str,
    offer_id: int,
    quantity: int,
    need: str,
    competing_unit_price: float | None = None,
    registry_item_id: int | None = None,
    purchase_id: int | None = None,
) -> Quote:
    """A quote for `quantity` of one catalog item. `need` says what the family asked for; `competing_unit_price` is
    the best online price the buyer found, if any."""
    competing = Decimal(str(competing_unit_price)) if competing_unit_price else None
    with SessionLocal() as db:
        q = market.request_quote(db, store, offer_id, quantity, need, competing, registry_item_id, purchase_id)
        return _quote(q)


@server.tool(title="Counter a quote")
def counter_offer(quote_id: int, unit_price: float, message: str = "") -> Quote:
    """Offer a lower unit price, once per quote. The store accepts it (status "countered") or answers with its lowest
    price (status "final")."""
    with SessionLocal() as db:
        return _quote(market.counter(db, quote_id, Decimal(str(unit_price)), message))


@server.tool(title="Accept a quote")
def accept_quote(quote_id: int, purchase_id: int | None = None) -> Quote:
    """Take the price on the table. The store reserves the stock; Hearthline pays through PayPal."""
    with SessionLocal() as db:
        return _quote(market.accept(db, quote_id, purchase_id))


@server.tool(title="Decline a quote")
def decline_quote(quote_id: int) -> Quote:
    """Tell the store you bought elsewhere."""
    with SessionLocal() as db:
        return _quote(market.decline(db, quote_id))


def internal_token() -> str:
    """What the Shopper presents to the store agents' endpoint: derived from the app's secret, never stored."""
    return hmac.new(get_settings().secret_key.encode(), b"hearthline-store-agents", hashlib.sha256).hexdigest()


class _RequireToken:
    """Only Hearthline's own Shopper may call the store agents over HTTP."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            given = headers.get(b"authorization", b"").decode()
            if not hmac.compare_digest(given, f"Bearer {internal_token()}"):
                await JSONResponse({"detail": "The store agents answer Hearthline's Shopper only"}, 401)(
                    scope, receive, send
                )
                return
        await self.app(scope, receive, send)


def http_app() -> Starlette:
    """Streamable HTTP at /mcp (mounted under /stores), stateless, behind the internal token."""
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver"]
    if host := get_settings().render_external_hostname:
        hosts.append(host)
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=[]),
    )
    app.add_middleware(_RequireToken)
    return app
