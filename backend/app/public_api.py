"""The public side of Hearthline, shared by the REST API (/v1) and the MCP server.

Anyone, or any agent, can find verified families' registries and local businesses' Reopen Funds, see
prices against their pre-disaster baseline, and *prepare* a gift. Money never moves here: preparing a gift
returns a PayPal link, and a person approves the payment there. Household addresses are never exposed.
"""

from datetime import datetime
from decimal import Decimal
from urllib.parse import urlencode

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import registry, reopen
from app.config import get_settings
from app.models import (
    Business,
    Case,
    DisasterEvent,
    Donation,
    GiftCard,
    PriceWatch,
    Purchase,
    Registry,
)
from app.paypal import orders

CENT = Decimal("0.01")


class PublicError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


# --- Shapes (these are the API's contract; APIMatic generates the SDKs from them) ---------------------


class Disaster(BaseModel):
    """A disaster Hearthline is responding to."""

    slug: str = Field(description="Stable id used in URLs", examples=["sablewood-fire"])
    name: str = Field(description="Public name", examples=["Sablewood Fire"])
    kind: str = Field(description="wildfire | flood | hurricane | earthquake", examples=["wildfire"])
    status: str = Field(description="active while Hearthline is responding", examples=["active"])
    declared_at: datetime = Field(description="When the state of emergency was declared (UTC)")
    price_protection_until: datetime | None = Field(description="Prices of essentials may rise at most 10% until then")
    is_fictional: bool = Field(description="True for the demo scenario (a fictional town)")


class RegistryItemInfo(BaseModel):
    """Something specific a family needs, and how much of it is paid for."""

    id: int = Field(description="Item id; pass it as `item_id` to give toward this item")
    name: str = Field(description="What the family needs", examples=["Twin mattresses"])
    note: str = Field(description="Why they need it, in the family's words")
    category: str = Field(
        description="Kind of item, e.g. bedding, clothing, electronics, kitchenware, tools", examples=["bedding"]
    )
    quantity: int = Field(description="How many")
    target_amount: Decimal = Field(description="Total needed for this item, in USD")
    funded_amount: Decimal = Field(description="Given so far, in USD")
    remaining: Decimal = Field(description="Still needed, in USD")
    status: str = Field(description="open | funded | purchased | delivered")


class RegistrySummary(BaseModel):
    """A verified family's Rebuild Registry. Shows the town, never the family's address."""

    slug: str = Field(description="Stable id used in URLs", examples=["rivera-family"])
    title: str = Field(description="The registry's title", examples=["Help the Riveras come home"])
    city: str = Field(description="Town", examples=["Sablewood"])
    state: str = Field(description="US state code", examples=["CA"])
    open_items: int = Field(description="Items that still need money")
    still_needed: Decimal = Field(description="Sum of what open items still need, in USD")
    url: str = Field(description="The registry's public page")


class RegistryDetail(RegistrySummary):
    """A registry with its story and every item."""

    story: str = Field(description="The family's story, in their words")
    items: list[RegistryItemInfo] = Field(description="Every item, most urgent first")


class Checkout(BaseModel):
    """A prepared payment. Nothing is charged until a person approves it at `approval_url`."""

    id: int = Field(description="Donation or gift card id")
    order_id: str = Field(description="PayPal order id")
    amount: Decimal = Field(description="USD")
    approval_url: str | None = Field(description="Open this to approve the payment with PayPal")
    status_url: str = Field(description="API URL to check the payment's status")
    note: str = Field(
        default="A person must approve this payment with PayPal. Nothing is charged until they do.",
        description="A reminder to show the person paying",
    )


class TimelineEvent(BaseModel):
    """One step in a gift's journey."""

    at: datetime | None = Field(description="When it happened (UTC); null if it hasn't yet")
    event: str = Field(description="What happened, in plain words", examples=["Delivered to the family"])


class DonationStatus(BaseModel):
    """Where a gift is: paid, the item bought, shipped and delivered."""

    id: int = Field(description="Donation id")
    status: str = Field(description="created (waiting for approval) | captured | failed | refunded")
    amount: Decimal = Field(description="USD")
    item: str | None = Field(description="The registry item it pays for; null for the household fund")
    timeline: list[TimelineEvent] = Field(description="What happened, in order")


class ReopenStep(BaseModel):
    """One step of a business's reopening plan. Staff release each step's money from escrow."""

    title: str = Field(description="What the money is for", examples=["Replace the ovens"])
    amount: Decimal = Field(description="USD")
    status: str = Field(description="pending | requested | released | rejected")


class ReopenFund(BaseModel):
    """A local business selling gift cards to pay for reopening. The money is held in escrow and refunded to
    buyers, from what's left, if the business misses its reopening date."""

    slug: str = Field(description="Stable id used in URLs", examples=["morenos-bakery"])
    business: str = Field(description="Business name", examples=["Moreno's Bakery"])
    kind: str = Field(description="bakery | restaurant | retail | services | other")
    city: str = Field(description="Town")
    status: str = Field(description="live | reopened | refunded | closed")
    goal_amount: Decimal = Field(description="What the reopening plan costs, in USD")
    raised: Decimal = Field(description="Paid for gift cards so far, in USD")
    bonus_percent: int = Field(description="A card is worth this much more in the shop than it costs")
    reopen_by: datetime = Field(description="The promised reopening date (UTC); escrow is refunded if missed")
    url: str = Field(description="The fund's public page")
    steps: list[ReopenStep] = Field(description="The reopening plan, in order")


class GiftCardStatus(BaseModel):
    """A Reopen gift card. Whoever has the code can spend it, so treat the code like cash."""

    code: str = Field(description="The card's code (also printed as a QR code)")
    business: str = Field(description="Where it can be spent")
    status: str = Field(description="active | refunded")
    face_value: Decimal = Field(description="What the card was worth when bought, in USD (price plus bonus)")
    balance: Decimal = Field(description="What's left to spend, in USD")
    usable_now: bool = Field(description="True once the business has reopened")


class PriceReport(BaseModel):
    """An essential item's price now against its price before the disaster (California Penal Code 396)."""

    title: str = Field(description="Product or service", examples=["Portable generator 3500W"])
    seller: str = Field(description="Store or local seller")
    category: str = Field(
        description="water | fuel | generator | lodging | medical | tools | building_materials | emergency_supplies"
    )
    source: str = Field(description="channel3 (online) | local_survey (demo data)")
    baseline_price: Decimal | None = Field(description="Median price in the 30 days before the declaration")
    current_price: Decimal | None = Field(description="Latest price seen, in USD")
    markup_percent: float | None = Field(description="Change from the baseline, in percent")
    status: str = Field(description="ok | gouging | no_baseline | unknown")


# --- Queries -----------------------------------------------------------------------------------------


def _web(path: str) -> str:
    return f"{get_settings().web_url}{path}"


def disasters(db: Session) -> list[Disaster]:
    return [Disaster.model_validate(e, from_attributes=True) for e in db.scalars(select(DisasterEvent))]


def _items(reg: Registry) -> list[RegistryItemInfo]:
    return [
        RegistryItemInfo(
            id=i.id,
            name=i.name,
            note=i.note,
            category=i.category,
            quantity=i.quantity,
            target_amount=i.target_amount,
            funded_amount=i.funded_amount,
            remaining=i.remaining,
            status=i.status,
        )
        for i in reg.items
    ]


def _summary(reg: Registry) -> RegistrySummary:
    items = [i for i in reg.items if i.status == "open"]
    return RegistrySummary(
        slug=reg.slug,
        title=reg.title,
        city=reg.household.city,
        state=reg.household.state,
        open_items=len(items),
        still_needed=sum((i.remaining for i in items), Decimal(0)),
        url=_web(f"/r/{reg.slug}"),
    )


OPEN_CASE = ("in_review", "needs_info", "escalated")
STOPWORDS = {"the", "and", "for", "with", "about", "from", "that", "this", "who", "need", "needs", "some", "any", "get"}


def find_registries(db: Session, query: str | None = None, limit: int = 20) -> list[RegistrySummary]:
    """Active registries, those with the most still needed first. A registry whose household has an open
    high-risk case (a suspected scam being reviewed) isn't recommended until reviewers decide."""
    flagged = set(db.scalars(select(Case.household_id).where(Case.status.in_(OPEN_CASE), Case.risk_tier == "high")))
    regs = [r for r in db.scalars(select(Registry).where(Registry.status == "active")) if r.household_id not in flagged]
    if query:  # any of the words, best matches first (agents send phrases like "winter coats for kids")
        words = [w for w in query.lower().replace(",", " ").split() if len(w) >= 3 and w not in STOPWORDS]

        def hits(r: Registry) -> int:
            text = " ".join([r.title, r.story, *(f"{i.name} {i.note}" for i in r.items)]).lower()
            return sum(1 for w in words if w in text or (w.endswith("s") and w[:-1] in text))

        scored = [(hits(r), r) for r in regs]
        regs = [r for n, r in sorted(scored, key=lambda x: -x[0]) if n > 0]
        return [_summary(r) for r in regs][:limit]
    out = sorted((_summary(r) for r in regs), key=lambda s: s.still_needed, reverse=True)
    return out[:limit]


def registry_detail(db: Session, slug: str) -> RegistryDetail:
    reg = db.scalar(select(Registry).where(Registry.slug == slug, Registry.status == "active"))
    if reg is None:
        raise PublicError("Registry not found", 404)
    return RegistryDetail(**_summary(reg).model_dump(), story=reg.story, items=_items(reg))


def start_donation(
    db: Session,
    slug: str,
    amount: Decimal,
    item_id: int | None = None,
    donor_name: str | None = None,
    message: str = "",
) -> Checkout:
    reg = db.scalar(select(Registry).where(Registry.slug == slug))
    if reg is None:
        raise PublicError("Registry not found", 404)
    amount = amount.quantize(CENT)
    try:
        donation = registry.new_donation(
            db,
            reg,
            item_id=item_id,
            amount=amount,
            donor_name=donor_name,
            message=message,
            payment_method="paypal",
            donor=None,
        )
    except registry.DonationError as e:
        raise PublicError(str(e), e.status) from None
    back = _web("/paid?" + urlencode({"kind": "donation", "id": donation.id}))
    item = donation.item
    donation.paypal_order_id, link = orders.create_order_with_link(
        amount=amount,
        description=f"Hearthline: {item.name if item else 'household fund'} for {reg.title}",
        custom_id=f"{registry.CUSTOM_ID_PREFIX}{donation.id}",
        reference_id=f"registry-{reg.id}",
        return_url=back,
        cancel_url=back + "&cancelled=1",
    )
    db.commit()
    return Checkout(
        id=donation.id,
        order_id=donation.paypal_order_id,
        amount=amount,
        approval_url=link,
        status_url=f"{get_settings().api_url}/v1/donations/{donation.id}",
    )


def donation_status(db: Session, donation_id: int) -> DonationStatus:
    d = db.get(Donation, donation_id)
    if d is None:
        raise PublicError("Donation not found", 404)
    timeline = [TimelineEvent(at=d.created_at, event="Gift prepared")]
    if d.captured_at:
        timeline.append(TimelineEvent(at=d.captured_at, event=f"Paid ${d.amount:.2f} with {d.payment_method}"))
    item = d.item
    if item is not None:
        if item.status in {"funded", "purchased", "delivered"}:
            timeline.append(TimelineEvent(at=None, event=f"{item.name} fully funded"))
        purchase = db.scalar(select(Purchase).where(Purchase.registry_item_id == item.id).order_by(Purchase.id.desc()))
        if purchase is not None:
            if purchase.paid_at:
                timeline.append(
                    TimelineEvent(
                        at=purchase.paid_at, event=f"Bought from {purchase.retailer} for ${purchase.total:.2f}"
                    )
                )
            if purchase.tracking_number:
                timeline.append(TimelineEvent(at=None, event=f"Shipped with {purchase.carrier}"))
            if purchase.status == "delivered":
                timeline.append(TimelineEvent(at=None, event="Delivered to the family"))
    return DonationStatus(
        id=d.id, status=d.status, amount=d.amount, item=item.name if item else None, timeline=timeline
    )


def _fund(b: Business) -> ReopenFund:
    c = b.campaigns[-1]
    return ReopenFund(
        slug=b.slug,
        business=b.name,
        kind=b.kind,
        city=b.city,
        status=c.status,
        goal_amount=c.goal_amount,
        raised=c.raised,
        bonus_percent=c.bonus_percent,
        reopen_by=c.reopen_by,
        url=_web(f"/reopen/{b.slug}"),
        steps=[ReopenStep(title=t.title, amount=t.amount, status=t.status) for t in c.tranches],
    )


def reopen_funds(db: Session, include_closed: bool = False) -> list[ReopenFund]:
    funds = [
        _fund(b)
        for b in db.scalars(select(Business).where(Business.verification == "verified").order_by(Business.id))
        if b.campaigns
    ]
    return funds if include_closed else [f for f in funds if f.status in {"live", "reopened"}]


def reopen_fund(db: Session, slug: str) -> ReopenFund:
    b = db.scalar(select(Business).where(Business.slug == slug, Business.verification == "verified"))
    if b is None or not b.campaigns:
        raise PublicError("Reopen Fund not found", 404)
    return _fund(b)


def start_gift_card(db: Session, slug: str, amount: Decimal, buyer_name: str | None = None) -> Checkout:
    b = db.scalar(select(Business).where(Business.slug == slug, Business.verification == "verified"))
    campaign = reopen.current_campaign(b) if b else None
    if campaign is None:
        raise PublicError("This Reopen Fund isn't selling cards right now", 404)
    amount = amount.quantize(CENT)
    try:
        card = reopen.start_card(db, campaign, amount, buyer_name, None, "paypal")
    except reopen.ReopenError as e:
        raise PublicError(str(e)) from None
    back = _web("/paid?" + urlencode({"kind": "gift_card", "id": card.id}))
    card.paypal_order_id, link = orders.create_order_with_link(
        amount=amount,
        description=f"Hearthline Reopen Fund: {b.name} gift card",
        custom_id=f"{reopen.CUSTOM_ID_PREFIX}{card.id}",
        reference_id=f"reopen-{campaign.id}",
        return_url=back,
        cancel_url=back + "&cancelled=1",
    )
    db.commit()
    return Checkout(
        id=card.id,
        order_id=card.paypal_order_id,
        amount=amount,
        approval_url=link,
        status_url=f"{get_settings().api_url}/v1/gift-cards/{card.code}",
    )


def gift_card(db: Session, code: str) -> GiftCardStatus:
    card = db.scalar(select(GiftCard).where(GiftCard.code == reopen.normalize_code(code)))
    if card is None or card.status in {"pending", "failed"}:
        raise PublicError("Gift card not found", 404)
    return GiftCardStatus(
        code=card.code,
        business=card.campaign.business.name,
        status=card.status,
        face_value=card.face_value,
        balance=card.balance,
        usable_now=card.status == "active" and card.campaign.status == "reopened",
    )


def price_report(db: Session, status: str | None = None, category: str | None = None) -> list[PriceReport]:
    q = select(PriceWatch).order_by(PriceWatch.markup_percent.desc().nulls_last())
    if status:
        q = q.where(PriceWatch.status == status)
    if category:
        q = q.where(PriceWatch.category == category)
    return [PriceReport.model_validate(w, from_attributes=True) for w in db.scalars(q)]
