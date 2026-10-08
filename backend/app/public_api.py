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
    slug: str = Field(examples=["sablewood-fire"])
    name: str = Field(examples=["Sablewood Fire"])
    kind: str = Field(examples=["wildfire"])
    status: str = Field(examples=["active"])
    declared_at: datetime
    price_protection_until: datetime | None = Field(description="Prices of essentials may rise at most 10% until then")
    is_fictional: bool


class RegistryItemInfo(BaseModel):
    id: int
    name: str = Field(examples=["Twin mattresses"])
    note: str
    category: str = Field(examples=["bedding"])
    quantity: int
    target_amount: Decimal = Field(description="Total needed for this item, in USD")
    funded_amount: Decimal
    remaining: Decimal
    status: str = Field(description="open | funded | purchased | delivered")


class RegistrySummary(BaseModel):
    slug: str = Field(examples=["rivera-family"])
    title: str = Field(examples=["Help the Riveras come home"])
    city: str
    state: str
    open_items: int
    still_needed: Decimal = Field(description="Sum of what open items still need, in USD")
    url: str = Field(description="The registry's public page")


class RegistryDetail(RegistrySummary):
    story: str
    items: list[RegistryItemInfo]


class Checkout(BaseModel):
    """A prepared payment. Nothing is charged until a person approves it at `approval_url`."""

    id: int = Field(description="Donation or gift card id")
    order_id: str = Field(description="PayPal order id")
    amount: Decimal
    approval_url: str | None = Field(description="Open this to approve the payment with PayPal")
    status_url: str = Field(description="API URL to check the payment's status")
    note: str = "A person must approve this payment with PayPal. Nothing is charged until they do."


class TimelineEvent(BaseModel):
    at: datetime | None
    event: str


class DonationStatus(BaseModel):
    id: int
    status: str = Field(description="created (waiting for approval) | captured | failed | refunded")
    amount: Decimal
    item: str | None
    timeline: list[TimelineEvent]


class ReopenStep(BaseModel):
    title: str
    amount: Decimal
    status: str = Field(description="pending | requested | released | rejected")


class ReopenFund(BaseModel):
    slug: str = Field(examples=["morenos-bakery"])
    business: str = Field(examples=["Moreno's Bakery"])
    kind: str
    city: str
    status: str = Field(description="live | reopened | refunded | closed")
    goal_amount: Decimal
    raised: Decimal
    bonus_percent: int = Field(description="A card is worth this much more in the shop than it costs")
    reopen_by: datetime
    url: str
    steps: list[ReopenStep]


class GiftCardStatus(BaseModel):
    code: str
    business: str
    status: str = Field(description="active | refunded")
    face_value: Decimal
    balance: Decimal
    usable_now: bool


class PriceReport(BaseModel):
    title: str
    seller: str
    category: str
    source: str = Field(description="channel3 (online) | local_survey (demo data)")
    baseline_price: Decimal | None = Field(description="Median price in the 30 days before the declaration")
    current_price: Decimal | None
    markup_percent: float | None
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


def find_registries(db: Session, query: str | None = None, limit: int = 20) -> list[RegistrySummary]:
    """Active (staff-verified) registries, those with the most still needed first."""
    regs = [r for r in db.scalars(select(Registry).where(Registry.status == "active"))]
    if query:
        q = query.lower()
        regs = [
            r for r in regs if q in r.title.lower() or q in r.story.lower() or any(q in i.name.lower() for i in r.items)
        ]
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
