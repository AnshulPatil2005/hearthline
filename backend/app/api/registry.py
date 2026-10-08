"""Rebuild Registry: the household manages it; anyone can view it and donate."""

import re
import secrets
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from paypalserversdk.exceptions.error_exception import ErrorException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, ledger, registry, review
from app.api.households import MyHousehold
from app.auth import CurrentUser, OptionalUser
from app.config import get_settings
from app.db import get_db
from app.models import Donation, Item, Registry, RegistryItem
from app.paypal import orders
from app.schemas import ORM, Money

router = APIRouter(tags=["registry"])
DB = Annotated[Session, Depends(get_db)]
MIN_DONATION = Decimal("1.00")


def paypal_reason(e: ErrorException) -> str:
    return getattr(e, "message", None) or getattr(e, "name", None) or "unknown error"


class RegistryItemOut(ORM):
    id: int
    name: str
    note: str
    category: str
    quantity: int
    unit_price: Money
    target_amount: Money
    funded_amount: Money
    remaining: Money
    status: str
    priority: int
    retailer: str | None
    match_url: str | None


class DonationOut(ORM):
    id: int
    donor_name: str | None
    message: str
    amount: Money
    payment_method: str
    item_name: str | None = None
    captured_at: datetime | None


class RegistryOut(ORM):
    slug: str
    title: str
    story: str
    status: str
    household_name: str
    city: str
    state: str
    disaster_name: str | None
    items: list[RegistryItemOut]
    total_target: Money
    total_funded: Money
    donor_count: int
    recent_donations: list[DonationOut]


class RegistryIn(BaseModel):
    title: str = Field(min_length=3, max_length=120)
    story: str = Field(default="", max_length=2000)


class RegistryItemIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    note: str = Field(default="", max_length=300)
    category: str = "other"
    quantity: int = Field(default=1, ge=1, le=50)
    unit_price: Money | None = Field(default=None, gt=0)
    priority: int = Field(default=100, ge=1, le=1000)
    inventory_item_id: int | None = None  # copy name and price from the household inventory


class DonationIn(BaseModel):
    item_id: int | None = None  # None = the household's general fund
    amount: Money = Field(ge=MIN_DONATION, le=Decimal("10000"))
    donor_name: str | None = Field(default=None, max_length=80)
    message: str = Field(default="", max_length=280)
    payment_method: Literal["paypal", "venmo", "paylater"] = "paypal"


class DonationCreated(BaseModel):
    donation_id: int
    order_id: str


class FundOut(BaseModel):
    available: Money
    donated: Money
    spent: Money


def registry_out(db: Session, reg: Registry) -> RegistryOut:
    home = reg.household
    items = [RegistryItemOut.model_validate(i) for i in reg.items]
    names = {i.id: i.name for i in reg.items}
    donations = []
    for d in registry.recent_donations(db, reg.id):
        out = DonationOut.model_validate(d)
        out.item_name = names.get(d.registry_item_id)
        donations.append(out)
    donors = db.scalars(select(Donation).where(Donation.registry_id == reg.id, Donation.status == "captured"))
    return RegistryOut(
        slug=reg.slug,
        title=reg.title,
        story=reg.story,
        status=reg.status,
        household_name=home.name,
        city=home.city,
        state=home.state,
        disaster_name=home.disaster_event.name if home.disaster_event else None,
        items=items,
        total_target=sum((i.target_amount for i in reg.items), Decimal(0)),
        total_funded=sum((i.funded_amount for i in reg.items), Decimal(0)),
        donor_count=len({d.donor_user_id or f"guest-{d.id}" for d in donors}),
        recent_donations=donations,
    )


def get_registry(db: Session, slug: str) -> Registry:
    reg = db.scalar(select(Registry).where(Registry.slug == slug))
    if reg is None:
        raise HTTPException(404, "Registry not found")
    return reg


def my_registry(db: Session, household_id: int) -> Registry:
    reg = db.scalar(select(Registry).where(Registry.household_id == household_id))
    if reg is None:
        raise HTTPException(404, "You haven't created a registry yet")
    return reg


# --- Household side -------------------------------------------------------------------------


@router.get("/households/me/registry", response_model=RegistryOut)
def get_my_registry(home: MyHousehold, db: DB) -> RegistryOut:
    return registry_out(db, my_registry(db, home.id))


@router.post("/households/me/registry", response_model=RegistryOut, status_code=201)
def create_registry(body: RegistryIn, home: MyHousehold, user: CurrentUser, db: DB) -> RegistryOut:
    if db.scalar(select(Registry).where(Registry.household_id == home.id)):
        raise HTTPException(409, "This household already has a registry")
    base = re.sub(r"[^a-z0-9]+", "-", home.name.lower()).strip("-")[:40]
    reg = Registry(
        household_id=home.id,
        slug=f"{base}-{secrets.token_hex(3)}",
        title=body.title,
        story=body.story,
        created_by_user_id=user.id,
        status="pending_review",  # goes public only after a human approves the verification case
    )
    db.add(reg)
    audit.record(db, actor_user_id=user.id, action="registry.created", subject_type="registry", subject_id=reg.slug)
    db.flush()
    review.open_case(
        db,
        home,
        kind="registry_verification",
        title=f"New registry: {body.title}",
        note=body.story[:500],
        actor_user_id=user.id,
    )
    return registry_out(db, reg)


@router.post("/households/me/registry/items", response_model=RegistryItemOut, status_code=201)
def add_registry_item(body: RegistryItemIn, home: MyHousehold, db: DB) -> RegistryItem:
    reg = my_registry(db, home.id)
    values = body.model_dump(exclude={"inventory_item_id"}, exclude_none=True)
    if body.inventory_item_id is not None:
        source = db.get(Item, body.inventory_item_id)
        if source is None or source.household_id != home.id:
            raise HTTPException(404, "Inventory item not found")
        values = {
            "name": source.name,
            "category": source.category,
            "quantity": source.quantity,
            "unit_price": source.unit_price,
            "channel3_product_id": source.channel3_product_id,
            "match_url": source.match_url,
            "retailer": source.retailer,
            "inventory_item_id": source.id,
        } | values
    if not values.get("name") or not values.get("unit_price"):
        raise HTTPException(422, "A registry item needs a name and a price")
    item = RegistryItem(registry_id=reg.id, **values)
    db.add(item)
    db.commit()
    return item


@router.delete("/households/me/registry/items/{item_id}", status_code=204)
def remove_registry_item(item_id: int, home: MyHousehold, db: DB) -> None:
    item = db.get(RegistryItem, item_id)
    if item is None or item.rebuild_registry.household_id != home.id:
        raise HTTPException(404, "Registry item not found")
    if item.funded_amount > 0:
        raise HTTPException(409, "Donors have already funded this item, so it can't be removed")
    db.delete(item)
    db.commit()


@router.get("/households/me/fund", response_model=FundOut)
def my_fund(home: MyHousehold, db: DB) -> FundOut:
    donated = sum(
        (
            d.amount
            for d in db.scalars(select(Donation).join(Registry).where(Registry.household_id == home.id))
            if d.status == "captured"
        ),
        Decimal(0),
    )
    available = ledger.household_available(db, home.id)
    return FundOut(available=available, donated=donated, spent=donated - available)


# --- Public side -----------------------------------------------------------------------------


@router.get("/paypal/client-id")
def paypal_client_id() -> dict:
    """Browser-safe client id for the PayPal JS SDK v6 (public by design)."""
    s = get_settings()
    return {"client_id": s.paypal_client_id, "environment": s.paypal_environment}


@router.get("/registries/{slug}", response_model=RegistryOut)
def view_registry(slug: str, db: DB) -> RegistryOut:
    """Public. Shows the town but never the household's address."""
    return registry_out(db, get_registry(db, slug))


@router.post("/registries/{slug}/donations", response_model=DonationCreated, status_code=201)
def start_donation(slug: str, body: DonationIn, donor: OptionalUser, db: DB) -> DonationCreated:
    reg = get_registry(db, slug)
    try:
        donation = registry.new_donation(
            db,
            reg,
            item_id=body.item_id,
            amount=body.amount,
            donor_name=body.donor_name,
            message=body.message,
            payment_method=body.payment_method,
            donor=donor,
        )
    except registry.DonationError as e:
        raise HTTPException(e.status, str(e)) from None
    item = donation.item
    try:
        donation.paypal_order_id = orders.create_order(
            amount=body.amount,
            description=f"Hearthline: {item.name if item else 'household fund'} for the {reg.household.name}",
            custom_id=f"{registry.CUSTOM_ID_PREFIX}{donation.id}",
            reference_id=f"registry-{reg.id}",
        )
    except ErrorException as e:
        db.rollback()
        raise HTTPException(502, f"PayPal couldn't start the payment: {paypal_reason(e)}") from None
    db.commit()
    return DonationCreated(donation_id=donation.id, order_id=donation.paypal_order_id)


@router.post("/donations/{donation_id}/capture", response_model=RegistryItemOut | DonationOut)
def capture_donation(donation_id: int, db: DB) -> RegistryItem | DonationOut:
    """Called after the donor approves in the PayPal/Venmo window. Returns the updated item."""
    donation = db.get(Donation, donation_id)
    if donation is None or donation.paypal_order_id is None:
        raise HTTPException(404, "Donation not found")
    if donation.status != "captured":
        try:
            capture = orders.capture_order(donation.paypal_order_id)
        except ErrorException as e:
            donation.status = "failed"
            db.commit()
            raise HTTPException(402, f"PayPal didn't complete the payment: {paypal_reason(e)}") from None
        registry.apply_capture(db, donation, capture)
        if capture.status != "COMPLETED":
            raise HTTPException(402, f"Payment is {capture.status.lower()}; it will update when PayPal confirms it")
    return donation.item if donation.item else DonationOut.model_validate(donation)
