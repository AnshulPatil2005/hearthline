"""Insurance claims paid through PayPal: the household prepares one and sends its private link to the insurer; the
adjuster reviews the claim, decides the amount and pays it with PayPal."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from paypalserversdk.exceptions.error_exception import ErrorException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import insurance_claims as svc
from app.api.households import MyHousehold
from app.api.registry import paypal_reason
from app.auth import CurrentUser
from app.config import get_settings
from app.db import get_db
from app.models import InsuranceClaim
from app.paypal import orders
from app.paypal_connect import mask
from app.schemas import Money

router = APIRouter(tags=["insurance-claims"])
DB = Annotated[Session, Depends(get_db)]


class ClaimStatus(BaseModel):
    """The claim as the household sees it."""

    id: int
    status: str
    insurer: str
    policy_number: str | None
    items: int
    inventory_value: Money
    estimate: Money
    link: str  # send this to the insurer's adjuster
    adjuster_name: str | None
    approved_amount: Money | None
    paid_at: datetime | None
    payout_status: str | None  # sent | held
    payout_to: str | None


def _status(claim: InsuranceClaim) -> ClaimStatus:
    return ClaimStatus(
        id=claim.id,
        status=claim.status,
        insurer=claim.insurer,
        policy_number=claim.policy_number,
        items=len(claim.items),
        inventory_value=claim.inventory_value,
        estimate=claim.estimate,
        link=f"{get_settings().web_url}/claim/{claim.token}",
        adjuster_name=claim.adjuster_name,
        approved_amount=claim.approved_amount,
        paid_at=claim.paid_at,
        payout_status=claim.payout_status,
        payout_to=mask(claim.household.payout_email),
    )


def _run(fn, *args):
    try:
        return fn(*args)
    except svc.ClaimError as e:
        raise HTTPException(e.status, str(e)) from e


@router.get("/households/me/claim", response_model=ClaimStatus | None)
def my_claim(home: MyHousehold, db: DB) -> ClaimStatus | None:
    claim = svc.current(db, home.id)
    return _status(claim) if claim else None


@router.post("/households/me/claim", response_model=ClaimStatus, status_code=201)
def prepare_claim(home: MyHousehold, user: CurrentUser, db: DB) -> ClaimStatus:
    """Build the claim from the inventory and the policy (again, if it hasn't been paid)."""
    return _status(_run(svc.prepare, db, home, user.id))


class PacketItemOut(BaseModel):
    name: str
    room: str | None
    category: str
    quantity: int
    value: Money
    evidence: str
    recorded_at: str | None
    photo_url: str | None
    price_source: str | None
    retailer: str | None
    sub_limit: str | None


class SubLimitOut(BaseModel):
    what: str
    limit: Money
    items_value: Money
    over_by: Money


class Packet(BaseModel):
    """What the insurer's adjuster sees."""

    status: str
    policyholder: str
    address: str
    insurer: str
    policy_number: str | None
    loss_date: date | None
    disaster: str | None
    items: list[PacketItemOut]
    sub_limits: list[SubLimitOut]
    inventory_value: Money
    contents_limit: Money | None
    deductible: Money | None
    estimate: Money
    adjuster_name: str | None
    approved_amount: Money | None
    paid_at: datetime | None
    payout_status: str | None


def _packet(claim: InsuranceClaim) -> Packet:
    home = claim.household
    return Packet(
        status=claim.status,
        policyholder=home.name,
        address=f"{home.address_line}, {home.city}, {home.state} {home.postal_code}",
        insurer=claim.insurer,
        policy_number=claim.policy_number,
        loss_date=claim.loss_date,
        disaster=home.disaster_event.name if home.disaster_event else None,
        items=[PacketItemOut(**vars(i)) for i in svc.packet_items(claim)],
        sub_limits=[
            SubLimitOut(**{k: s[k] for k in ("what", "limit", "items_value", "over_by")}) for s in claim.sub_limits
        ],
        inventory_value=claim.inventory_value,
        contents_limit=claim.contents_limit,
        deductible=claim.deductible,
        estimate=claim.estimate,
        adjuster_name=claim.adjuster_name,
        approved_amount=claim.approved_amount,
        paid_at=claim.paid_at,
        payout_status=claim.payout_status,
    )


@router.get("/claims/{token}", response_model=Packet)
def claim_packet(token: str, db: DB) -> Packet:
    """The adjuster's view, by the private link the household sent."""
    return _packet(_run(svc.by_token, db, token))


class PayIn(BaseModel):
    amount: Decimal = Field(gt=0)
    adjuster_name: str = Field(min_length=2, max_length=120)
    note: str = Field(default="", max_length=500)


class OrderOut(BaseModel):
    order_id: str


@router.post("/claims/{token}/order", response_model=OrderOut)
def start_claim_payment(token: str, body: PayIn, db: DB) -> OrderOut:
    """The adjuster approved an amount: the PayPal order they pay with the insurer's PayPal account."""
    claim = _run(svc.by_token, db, token)
    return OrderOut(order_id=_run(svc.start_payment, db, claim, body.amount, body.adjuster_name, body.note))


@router.post("/claims/{token}/capture", response_model=Packet)
def capture_claim_payment(token: str, db: DB) -> Packet:
    """After the adjuster approves in PayPal's window: capture, then pay the household's PayPal account."""
    claim = _run(svc.by_token, db, token)
    if claim.status != "paid":
        if not claim.paypal_order_id:
            raise HTTPException(409, "Start the payment first")
        try:
            capture = orders.capture_order(claim.paypal_order_id)
        except ErrorException as e:
            raise HTTPException(402, f"PayPal didn't complete the payment: {paypal_reason(e)}") from None
        svc.complete(db, claim, capture)
        if capture.status != "COMPLETED":
            raise HTTPException(402, f"Payment is {capture.status.lower()}; it will update when PayPal confirms it")
    return _packet(claim)
