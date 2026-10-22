"""The Shopper's side of the agent marketplace: before buying a need online, Hearthline's Shopper asks local stores'
pricing agents for quotes over MCP (`app.store_mcp`), may counter the lowest once, and takes the best price within
its limit. Code sets the limit (what donors gave for the item, and no more than 15% above the online offer it would
otherwise buy) and every message it sends; the stores' agents set their prices within their owners' rules. The whole
exchange is kept on the purchase for the family and donors to read.
"""

import asyncio
import logging
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from app import store_mcp
from app.config import get_settings

log = logging.getLogger(__name__)

SHOPPER = "Hearthline's Shopper"


@dataclass(frozen=True)
class Ask:
    store_slug: str
    store: str
    offer_id: int
    title: str


@dataclass(frozen=True)
class Deal:
    quote_id: int
    store_slug: str
    store: str
    offer_id: int
    unit_price: Decimal
    list_price: Decimal
    delivery_days: int
    countered: bool


@dataclass(frozen=True)
class Outcome:
    deal: Deal | None
    transcript: list[dict[str, str | None]]
    summary: str


def connect() -> Client:
    """The store agents over Streamable HTTP with Hearthline's internal token (tests connect to the server itself)."""
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {store_mcp.internal_token()}"}, timeout=60)
    return Client(streamable_http_client(f"{get_settings().api_url}/stores/mcp", http_client=http))


def _cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _said(result: Any) -> str:
    return " ".join(getattr(c, "text", "") for c in (result.content or [])).strip()


async def _call(stores: Client, tool: str, args: dict[str, Any]) -> dict[str, Any] | str:
    """A tool's structured answer, or the store's refusal as text."""
    result = await stores.call_tool(tool, args)
    if result.is_error or result.structured_content is None:
        return _said(result) or "The store's agent couldn't answer"
    return dict(result.structured_content)


async def _negotiate(
    asks: list[Ask],
    quantity: int,
    limit: Decimal,
    need: str,
    competing: Decimal | None,
    reason: str,
    registry_item_id: int | None,
    purchase_id: int | None,
) -> Outcome:
    transcript: list[dict[str, str | None]] = []
    quotes: list[dict[str, Any]] = []

    def said(who: str, to: str, text: str, price: str | None = None) -> None:
        transcript.append({"from": who, "to": to, "text": text, "unit_price": price})

    async with connect() as stores:
        for ask in asks:
            asked = f"Could you quote {quantity} × {ask.title}? A family who lost their home needs {need}."
            if competing:
                asked += f" The best online price we found is ${competing:,.2f} each."
            said(SHOPPER, ask.store, asked)
            got = await _call(
                stores,
                "request_quote",
                {
                    "store": ask.store_slug,
                    "offer_id": ask.offer_id,
                    "quantity": quantity,
                    "need": need,
                    "competing_unit_price": float(competing) if competing else None,
                    "registry_item_id": registry_item_id,
                    "purchase_id": purchase_id,
                },
            )
            if isinstance(got, str):
                said(ask.store, SHOPPER, got)
                continue
            got["slug"] = ask.store_slug
            quotes.append(got)
            said(ask.store, SHOPPER, got["message"], got["unit_price"])

        if not quotes:
            return Outcome(None, transcript, "No local store could quote it.")
        price = lambda q: Decimal(q["unit_price"])  # noqa: E731
        within = [q for q in quotes if price(q) <= limit]
        winner, countered = None, False
        if within:
            winner = min(within, key=lambda q: (price(q), q["delivery_days"]))
        else:
            lowest = min(quotes, key=price)
            offer = _cents(limit)
            text = f"The most we can pay is ${offer:,.2f} each: {reason}. Could you do that?"
            said(SHOPPER, lowest["store"], text, str(offer))
            got = await _call(
                stores, "counter_offer", {"quote_id": lowest["quote_id"], "unit_price": float(offer), "message": text}
            )
            if isinstance(got, str):
                said(lowest["store"], SHOPPER, got)
            else:
                said(lowest["store"], SHOPPER, got["message"], got["unit_price"])
                got["slug"] = lowest["slug"]
                quotes = [got if q["quote_id"] == got["quote_id"] else q for q in quotes]
                if got["status"] == "countered" and price(got) <= limit:
                    winner, countered = got, True

        deal = None
        if winner is not None:
            taken = await _call(stores, "accept_quote", {"quote_id": winner["quote_id"], "purchase_id": purchase_id})
            if isinstance(taken, str):
                said(winner["store"], SHOPPER, taken)
            else:
                said(SHOPPER, winner["store"], f"Deal at ${price(taken):,.2f} each. Payment follows through PayPal.")
                deal = Deal(
                    quote_id=taken["quote_id"],
                    store_slug=winner["slug"],
                    store=taken["store"],
                    offer_id=taken["offer_id"],
                    unit_price=price(taken),
                    list_price=Decimal(taken["list_price"]),
                    delivery_days=taken["delivery_days"],
                    countered=countered,
                )
        for q in quotes:
            if deal is None or q["quote_id"] != deal.quote_id:
                await _call(stores, "decline_quote", {"quote_id": q["quote_id"]})

    others = [q for q in quotes if deal is None or q["quote_id"] != deal.quote_id]
    elsewhere = "; ".join(f"{q['store']} offered ${price(q):,.2f}" for q in others)
    if deal is not None:
        if deal.unit_price < deal.list_price:
            how = " after a counter-offer" if deal.countered else ""
            summary = f"{deal.store} agreed to ${deal.unit_price:,.2f} each (list ${deal.list_price:,.2f}){how}."
        else:
            summary = f"{deal.store} quoted ${deal.unit_price:,.2f} each."
        return Outcome(deal, transcript, summary + (f" {elsewhere}." if elsewhere else ""))
    return Outcome(
        None, transcript, f"Local stores were asked first, but none could meet ${limit:,.2f} each ({elsewhere})."
    )


def negotiate(
    asks: list[Ask],
    *,
    quantity: int,
    limit: Decimal,
    need: str,
    competing: Decimal | None,
    reason: str,
    registry_item_id: int | None = None,
    purchase_id: int | None = None,
) -> Outcome:
    """Run the exchange (the Shopper runs in a worker thread, so it has its own event loop). If the store agents
    can't be reached, the Shopper buys online as before."""
    try:
        return asyncio.run(_negotiate(asks, quantity, limit, need, competing, reason, registry_item_id, purchase_id))
    except Exception:  # noqa: BLE001 - a marketplace failure must never stop the family's purchase
        log.exception("Talking to the local stores' agents failed")
        return Outcome(None, [], "Local stores couldn't be reached, so the Shopper bought online.")
