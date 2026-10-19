import secrets
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, shopping
from app.api.households import MyHousehold
from app.auth import CurrentUser
from app.db import get_db
from app.models import Purchase, RegistryItem
from app.schemas import ORM, Money

router = APIRouter(tags=["purchases"])
DB = Annotated[Session, Depends(get_db)]


class CheckOut(ORM):
    rule: str
    passed: bool
    detail: str


class PurchaseOut(ORM):
    id: int
    registry_item_id: int | None
    title: str
    retailer: str
    url: str | None
    unit_price: Money
    quantity: int
    total: Money
    status: str
    policy_checks: list[CheckOut]
    refused_offers: list[dict] = []  # offers the price-gouging guard turned down
    ai_reasoning: str
    ai_confidence: float | None
    candidates_considered: int
    payment_rail: str
    local_business_id: int | None = None  # bought from a local business (it delivers)
    paypal_ref: str | None
    carrier: str | None
    tracking_number: str | None
    error: str | None
    created_at: datetime
    paid_at: datetime | None


def own_purchase(db: Session, household_id: int, purchase_id: int) -> Purchase:
    purchase = db.get(Purchase, purchase_id)
    if purchase is None or purchase.household_id != household_id:
        raise HTTPException(404, "Purchase not found")
    return purchase


@router.get("/households/me/purchases", response_model=list[PurchaseOut])
def list_purchases(home: MyHousehold, db: DB) -> list[Purchase]:
    return list(db.scalars(select(Purchase).where(Purchase.household_id == home.id).order_by(Purchase.id.desc())))


@router.post("/households/me/registry/items/{item_id}/shop", response_model=PurchaseOut, status_code=201)
def shop_now(item_id: int, home: MyHousehold, db: DB) -> Purchase:
    """Run the Shopper agent for a funded item right away (it also runs automatically when funded)."""
    item = db.get(RegistryItem, item_id)
    if item is None or item.rebuild_registry.household_id != home.id:
        raise HTTPException(404, "Registry item not found")
    if item.funded_amount <= Decimal(0):
        raise HTTPException(409, "Nothing has been donated for this item yet")
    if item.status in {"purchased", "delivered"}:
        raise HTTPException(409, "This item has already been bought")
    return shopping.plan_purchase(db, item)


@router.post("/purchases/{purchase_id}/approve", response_model=PurchaseOut)
def approve(purchase_id: int, home: MyHousehold, user: CurrentUser, db: DB) -> Purchase:
    purchase = own_purchase(db, home.id, purchase_id)
    if purchase.status != "awaiting_approval":
        raise HTTPException(409, f"Purchase is {purchase.status}")
    audit.record(db, actor_user_id=user.id, action="purchase.approved", subject_type="purchase", subject_id=purchase.id)
    return shopping.execute(db, purchase, approved_by=user.id)


@router.post("/purchases/{purchase_id}/reject", response_model=PurchaseOut)
def reject(purchase_id: int, home: MyHousehold, user: CurrentUser, db: DB) -> Purchase:
    purchase = own_purchase(db, home.id, purchase_id)
    if purchase.status != "awaiting_approval":
        raise HTTPException(409, f"Purchase is {purchase.status}")
    purchase.status = "rejected"
    audit.record(db, actor_user_id=user.id, action="purchase.rejected", subject_type="purchase", subject_id=purchase.id)
    db.commit()
    return purchase


@router.post("/purchases/{purchase_id}/simulate-shipping", response_model=PurchaseOut)
def simulate_shipping(purchase_id: int, home: MyHousehold, db: DB) -> Purchase:
    """Demo only: move a paid purchase to shipped (with a tracking number), then to delivered."""
    purchase = own_purchase(db, home.id, purchase_id)
    if purchase.status == "paid":
        purchase.status, purchase.carrier = "shipped", "UPS"
        purchase.tracking_number = f"1Z{secrets.token_hex(8).upper()}"
    elif purchase.status == "shipped":
        purchase.status = "delivered"
        if purchase.registry_item is not None:
            purchase.registry_item.status = "delivered"
    else:
        raise HTTPException(409, f"Purchase is {purchase.status}")
    shared = shopping.share_tracking(db, purchase) if purchase.status == "shipped" else 0
    audit.record(
        db,
        action=f"purchase.{purchase.status}",
        subject_type="purchase",
        subject_id=purchase.id,
        data={"tracking": purchase.tracking_number, "added_to_paypal_payments": shared},
    )
    db.commit()
    return purchase
