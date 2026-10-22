"""The store side of the agent marketplace: quotes from local stores' pricing agents to Hearthline's Shopper.

Each open, verified store sells through a pricing agent that Hearthline hosts for it (`app.agents.store`), reached by
the Shopper over MCP (`app.store_mcp`). A quote is a record the store keeps: the price on the table, the messages, and
how it ended. The Shopper may counter once; accepting a quote reserves the stock.
"""

from decimal import Decimal

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app import local_first
from app.agents import store as store_agent
from app.models import Business, LocalOffer, MarketQuote, now

DELIVERY_DAYS = 1  # local stores deliver in town (or the family picks up) the next day
SHOPPER = "Hearthline's Shopper"


class MarketError(ValueError):
    """The store's agent can't do what was asked (closed, out of stock, a quote already settled)."""


def _store(db: Session, slug: str) -> Business:
    business = db.scalar(select(Business).where(Business.slug == slug))
    if business is None or not local_first.open_now(business):
        raise MarketError(f"No open store called {slug}")
    return business


def catalog(db: Session, slug: str) -> list[LocalOffer]:
    business = _store(db, slug)
    return list(
        db.scalars(
            select(LocalOffer)
            .where(LocalOffer.business_id == business.id, LocalOffer.available, LocalOffer.stock > 0)
            .order_by(LocalOffer.id)
        )
    )


def request_quote(
    db: Session,
    slug: str,
    offer_id: int,
    quantity: int,
    need: str,
    competing: Decimal | None,
    registry_item_id: int | None = None,
    purchase_id: int | None = None,
) -> MarketQuote:
    business = _store(db, slug)
    offer = db.get(LocalOffer, offer_id)
    if offer is None or offer.business_id != business.id or not offer.available:
        raise MarketError(f"{business.name} doesn't sell that")
    if quantity < 1:
        raise MarketError("Ask for at least one")
    if offer.stock < quantity:
        raise MarketError(f"{business.name} has only {offer.stock} in stock")
    answer = store_agent.opening(
        store=business.name,
        owner_note=business.agent_note,
        item=offer.title,
        need=need,
        list_price=offer.unit_price,
        floor=offer.floor,
        quantity=quantity,
        delivery_days=DELIVERY_DAYS,
        competing=competing,
    )
    asked = f"Could you quote {quantity} × {offer.title}? A family who lost their home needs {need}."
    if competing:
        asked += f" The best online price we found is ${competing:,.2f} each."
    quote = MarketQuote(
        business_id=business.id,
        offer_id=offer.id,
        registry_item_id=registry_item_id,
        purchase_id=purchase_id,
        quantity=quantity,
        list_price=offer.unit_price,
        unit_price=answer.unit_price,
        delivery_days=DELIVERY_DAYS,
        by_ai=answer.by_ai,
        messages=[
            {"from": SHOPPER, "text": asked, "unit_price": None},
            {"from": business.name, "text": answer.message, "unit_price": str(answer.unit_price)},
        ],
    )
    db.add(quote)
    db.commit()
    return quote


def _quote(db: Session, quote_id: int, *statuses: str) -> MarketQuote:
    quote = db.get(MarketQuote, quote_id)
    if quote is None:
        raise MarketError("No such quote")
    if quote.status not in statuses:
        raise MarketError(f"This quote is already {quote.status}")
    return quote


def counter(db: Session, quote_id: int, unit_price: Decimal, message: str) -> MarketQuote:
    """One counter-offer per quote. The store's agent accepts at or above the floor; otherwise its floor is final."""
    quote = _quote(db, quote_id, "quoted")
    answer, accepted = store_agent.reply_to_counter(
        store=quote.business.name,
        owner_note=quote.business.agent_note,
        item=quote.offer.title,
        counter=unit_price,
        floor=quote.offer.floor,
        current=quote.unit_price,
    )
    quote.messages = [
        *quote.messages,
        {"from": SHOPPER, "text": message.strip()[:400], "unit_price": str(unit_price)},
        {"from": quote.business.name, "text": answer.message, "unit_price": str(answer.unit_price)},
    ]
    quote.unit_price = answer.unit_price
    quote.status = "countered" if accepted else "final"
    quote.by_ai = quote.by_ai or answer.by_ai
    db.commit()
    return quote


def accept(db: Session, quote_id: int, purchase_id: int | None = None) -> MarketQuote:
    """The Shopper takes the price on the table: reserve the stock, atomically, so two buyers can't take the last
    one."""
    quote = _quote(db, quote_id, "quoted", "countered", "final")
    reserved = db.execute(
        update(LocalOffer)
        .where(LocalOffer.id == quote.offer_id, LocalOffer.stock >= quote.quantity)
        .values(stock=LocalOffer.stock - quote.quantity)
        .execution_options(synchronize_session=False)
    ).rowcount
    if reserved != 1:
        db.rollback()
        raise MarketError(f"{quote.business.name} sold out of that in the meantime")
    quote.status, quote.decided_at = "accepted", now()
    if purchase_id is not None:
        quote.purchase_id = purchase_id
    db.commit()
    return quote


def decline(db: Session, quote_id: int) -> MarketQuote:
    """The Shopper bought elsewhere."""
    quote = _quote(db, quote_id, "quoted", "countered", "final")
    quote.status, quote.decided_at = "declined", now()
    db.commit()
    return quote
