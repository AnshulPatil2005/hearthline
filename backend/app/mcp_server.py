"""The Hearthline MCP server: the public API as tools for AI agents (Claude, ChatGPT, any MCP client).

Served over Streamable HTTP at /mcp by the same app as the REST API. An agent can find families' registries
and local Reopen Funds, check prices for gouging, and prepare a gift. It cannot pay: preparing a gift returns
a PayPal link that the person it's helping opens to approve the payment.
"""

from decimal import Decimal

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from app import public_api as svc
from app.config import get_settings
from app.db import SessionLocal

INSTRUCTIONS = """Hearthline helps people recover after disasters. Use these tools to help someone give well:
find verified families' Rebuild Registries (specific things they need) or local businesses' Reopen Funds
(gift cards that pay for reopening), explain what the money will do, and prepare the gift.
Preparing a gift never charges anyone: it returns a PayPal approval link. Always show that link to the person
and tell them they approve the payment on PayPal. Never ask for card numbers or PayPal passwords.
Household addresses are private and not available."""

server = MCPServer(
    name="hearthline",
    title="Hearthline",
    description="Disaster recovery giving: registries, Reopen Funds and price-gouging data, with PayPal checkout.",
    instructions=INSTRUCTIONS,
    version="1.0.0",
)


@server.tool(title="Find registries")
def find_registries(query: str | None = None, limit: int = 10) -> list[svc.RegistrySummary]:
    """Families' verified Rebuild Registries, those that still need the most first.
    `query` matches words in the title, story or items (e.g. "mattress", "laptop")."""
    with SessionLocal() as db:
        return svc.find_registries(db, query, min(max(limit, 1), 50))


@server.tool(title="Get a registry")
def get_registry(slug: str) -> svc.RegistryDetail:
    """A registry's story and every item with what it still needs."""
    with SessionLocal() as db:
        return svc.registry_detail(db, slug)


@server.tool(title="Prepare a donation")
def prepare_donation(
    slug: str, amount: float, item_id: int | None = None, donor_name: str | None = None, message: str = ""
) -> svc.Checkout:
    """Prepare a gift to a family (USD). Give `item_id` to fund one item, or leave it out for the household
    fund. Returns a PayPal approval link: show it to the person; nothing is charged until they approve."""
    with SessionLocal() as db:
        return svc.start_donation(
            db, slug, Decimal(str(amount)).quantize(Decimal("0.01")), item_id, donor_name, message
        )


@server.tool(title="Check a donation")
def donation_status(donation_id: int) -> svc.DonationStatus:
    """Where a gift went: paid, the item bought by Hearthline's Shopper, shipped, delivered."""
    with SessionLocal() as db:
        return svc.donation_status(db, donation_id)


@server.tool(title="Find Reopen Funds")
def find_reopen_funds() -> list[svc.ReopenFund]:
    """Local businesses closed by the disaster that sell gift cards to pay for reopening (often with a bonus)."""
    with SessionLocal() as db:
        return svc.reopen_funds(db)


@server.tool(title="Prepare a gift card")
def prepare_gift_card(slug: str, amount: float, buyer_name: str | None = None) -> svc.Checkout:
    """Prepare a gift card purchase ($10 to $500) from a Reopen Fund. Returns a PayPal approval link.
    If the business doesn't reopen by its date, buyers are refunded what's left in escrow."""
    with SessionLocal() as db:
        return svc.start_gift_card(db, slug, Decimal(str(amount)).quantize(Decimal("0.01")), buyer_name)


@server.tool(title="Check prices for gouging")
def price_watch(status: str | None = None, category: str | None = None) -> list[svc.PriceReport]:
    """Essential prices in the disaster area against their pre-disaster baseline. California limits increases
    to 10% (Penal Code 396). `status` can be "gouging" to list only sellers over the limit."""
    with SessionLocal() as db:
        return svc.price_report(db, status, category)


def http_app() -> Starlette:
    """Streamable HTTP at /mcp. Host checks guard against DNS rebinding: local hosts plus our Render host."""
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver"]
    if host := get_settings().render_external_hostname:
        hosts.append(host)
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,  # each call stands alone, so any server instance can answer it
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=[]),
    )
