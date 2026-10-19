"""A local business's side of "local first": what it sells to families through Hearthline's Shopper, the orders the
Shopper placed (already paid through PayPal), and marking them delivered."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, local_first
from app.api.reopen import MyBusiness, Owner
from app.db import get_db
from app.models import Household, LocalOffer, Purchase
from app.schemas import Money

router = APIRouter(prefix="/businesses/me", tags=["local-shop"])
DB = Annotated[Session, Depends(get_db)]


class OfferIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    category: str = Field(min_length=2, max_length=60)
    unit_price: Decimal = Field(gt=0, le=5000)


class OfferOut(BaseModel):
    id: int
    title: str
    category: str
    unit_price: Money
    available: bool


class Shop(BaseModel):
    open: bool  # the Shopper only buys from verified businesses that are open
    offers: list[OfferOut]


def _shop(db: Session, b) -> Shop:
    offers = db.scalars(select(LocalOffer).where(LocalOffer.business_id == b.id).order_by(LocalOffer.id))
    return Shop(open=local_first.open_now(b), offers=[OfferOut.model_validate(o, from_attributes=True) for o in offers])


@router.get("/offers", response_model=Shop)
def my_offers(b: MyBusiness, db: DB) -> Shop:
    return _shop(db, b)


@router.post("/offers", response_model=Shop, status_code=201)
def add_offer(body: OfferIn, b: MyBusiness, db: DB) -> Shop:
    db.add(LocalOffer(business_id=b.id, title=body.title.strip(), category=body.category, unit_price=body.unit_price))
    db.commit()
    return _shop(db, b)


class AvailableIn(BaseModel):
    available: bool


def _offer(db: Session, b, offer_id: int) -> LocalOffer:
    offer = db.get(LocalOffer, offer_id)
    if offer is None or offer.business_id != b.id:
        raise HTTPException(404, "Not found")
    return offer


@router.patch("/offers/{offer_id}", response_model=Shop)
def set_available(offer_id: int, body: AvailableIn, b: MyBusiness, db: DB) -> Shop:
    _offer(db, b, offer_id).available = body.available
    db.commit()
    return _shop(db, b)


@router.delete("/offers/{offer_id}", response_model=Shop)
def remove_offer(offer_id: int, b: MyBusiness, db: DB) -> Shop:
    db.delete(_offer(db, b, offer_id))
    db.commit()
    return _shop(db, b)


class OrderOut(BaseModel):
    id: int
    title: str
    quantity: int
    total: Money
    status: str
    paid_at: datetime | None
    family: str
    # Who to hand it to. The verified address is often the damaged home, so the store arranges pickup or delivery
    # with the family's contact and checks their name when handing it over.
    contact_name: str
    contact_email: str


@router.get("/orders", response_model=list[OrderOut])
def my_orders(b: MyBusiness, db: DB) -> list[OrderOut]:
    """Orders Hearthline's Shopper placed and paid for, newest first."""
    rows = db.execute(
        select(Purchase, Household)
        .join(Household, Purchase.household_id == Household.id)
        .where(Purchase.local_business_id == b.id, Purchase.status.in_(("paid", "shipped", "delivered")))
        .order_by(Purchase.id.desc())
    )
    return [
        OrderOut(
            id=p.id,
            title=p.title,
            quantity=p.quantity,
            total=p.total,
            status=p.status,
            paid_at=p.paid_at,
            family=h.name,
            contact_name=contact.name if contact else h.name,
            contact_email=contact.email if contact else "",
        )
        for p, h in rows
        for contact in [min(h.members, key=lambda u: u.id, default=None)]
    ]


@router.post("/orders/{purchase_id}/delivered", response_model=list[OrderOut])
def mark_delivered(purchase_id: int, b: MyBusiness, owner: Owner, db: DB) -> list[OrderOut]:
    purchase = db.get(Purchase, purchase_id)
    if purchase is None or purchase.local_business_id != b.id:
        raise HTTPException(404, "Not found")
    if purchase.status not in ("paid", "shipped"):
        raise HTTPException(409, f"This order is {purchase.status}")
    purchase.status = "delivered"
    if purchase.registry_item is not None:
        purchase.registry_item.status = "delivered"
    audit.record(
        db,
        actor_user_id=owner.id,
        action="purchase.delivered",
        subject_type="purchase",
        subject_id=purchase.id,
        data={"by": b.name, "local": True},
    )
    db.commit()
    return my_orders(b, db)
