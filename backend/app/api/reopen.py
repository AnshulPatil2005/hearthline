"""Reopen Fund endpoints: the public campaign page and gift cards, the business owner's app, staff review,
and the reopening plan for Bryntum Gantt."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, HTTPException
from paypalserversdk.exceptions.error_exception import ErrorException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, reopen
from app.api.registry import paypal_reason
from app.auth import OptionalUser, require_role
from app.config import get_settings
from app.db import get_db
from app.models import Business, GiftCard, ReopenCampaign, ReopenRegular, ReopenTranche, Role, User
from app.paypal import orders
from app.schemas import Money

router = APIRouter(tags=["reopen"])
DB = Annotated[Session, Depends(get_db)]
Owner = Annotated[User, Depends(require_role(Role.BUSINESS))]
OrgStaff = Annotated[User, Depends(require_role(Role.ORG_ADMIN, Role.SUPERVISOR))]


def run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except reopen.ReopenError as e:
        raise HTTPException(409, str(e)) from None


# --- Shapes -------------------------------------------------------------------------------------------


class TrancheOut(BaseModel):
    id: int
    seq: int
    title: str
    amount: Money
    start_date: datetime
    end_date: datetime
    status: str
    request_note: str | None = None
    decision_note: str | None = None
    released_at: datetime | None = None


class CampaignOut(BaseModel):
    id: int
    goal_amount: Money
    raised: Money
    bonus_percent: int
    reopen_by: datetime
    status: str
    cards_sold: int
    escrow: Money
    released: Money
    redeemed: Money
    reopened_at: datetime | None
    refunded_at: datetime | None
    tranches: list[TrancheOut]
    regular_monthly: Money
    regular_months: int
    regulars: int


class BusinessOut(BaseModel):
    id: int
    name: str
    slug: str
    kind: str
    city: str
    state: str
    story: str
    verification: str
    verification_note: str | None
    campaign: CampaignOut | None


class PublicCampaignOut(BusinessOut):
    supporters: list[str]  # first names of recent buyers


class CardOut(BaseModel):
    code: str
    business_name: str
    business_slug: str
    amount_paid: Money
    face_value: Money
    balance: Money
    status: str
    campaign_status: str
    reopen_by: datetime
    refunded_amount: Money


class CardRow(BaseModel):
    id: int
    code_end: str
    buyer: str | None
    amount_paid: Money
    face_value: Money
    balance: Money
    status: str
    payment_method: str
    activated_at: datetime | None


def campaign_out(db: Session, c: ReopenCampaign) -> CampaignOut:
    active = [card for card in c.cards if card.status in {"active", "refunded"}]
    return CampaignOut(
        id=c.id,
        goal_amount=c.goal_amount,
        raised=c.raised,
        bonus_percent=c.bonus_percent,
        reopen_by=c.reopen_by,
        status=c.status,
        cards_sold=len(active),
        escrow=reopen.escrow_balance(db, c.id),
        released=sum((t.amount for t in c.tranches if t.status == "released"), Decimal(0)),
        redeemed=sum((r.amount for card in active for r in card.redemptions), Decimal(0)),
        reopened_at=c.reopened_at,
        refunded_at=c.refunded_at,
        tranches=[TrancheOut.model_validate(t, from_attributes=True) for t in c.tranches],
        regular_monthly=c.regular_monthly,
        regular_months=c.regular_months,
        regulars=db.scalar(
            select(func.count(ReopenRegular.id)).where(
                ReopenRegular.campaign_id == c.id, ReopenRegular.status == "active"
            )
        ),
    )


def business_out(db: Session, b: Business) -> BusinessOut:
    campaign = reopen.current_campaign(b) or (b.campaigns[-1] if b.campaigns else None)
    return BusinessOut(
        id=b.id,
        name=b.name,
        slug=b.slug,
        kind=b.kind,
        city=b.city,
        state=b.state,
        story=b.story,
        verification=b.verification,
        verification_note=b.verification_note,
        campaign=campaign_out(db, campaign) if campaign else None,
    )


def card_out(card: GiftCard) -> CardOut:
    c = card.campaign
    return CardOut(
        code=card.code,
        business_name=c.business.name,
        business_slug=c.business.slug,
        amount_paid=card.amount_paid,
        face_value=card.face_value,
        balance=card.balance,
        status=card.status,
        campaign_status=c.status,
        reopen_by=c.reopen_by,
        refunded_amount=card.refunded_amount,
    )


# --- Public: the campaign page and buying a card ------------------------------------------------------


def business_by_slug(db: Session, slug: str) -> Business:
    b = db.scalar(select(Business).where(Business.slug == slug))
    if b is None or b.verification != "verified" or not b.campaigns:
        raise HTTPException(404, "Reopen Fund not found")
    return b


@router.get("/reopen/{slug}", response_model=PublicCampaignOut)
def view_campaign(slug: str, db: DB) -> PublicCampaignOut:
    b = business_by_slug(db, slug)
    out = business_out(db, b)
    campaign = b.campaigns[-1]
    recent = [c for c in reversed(campaign.cards) if c.status == "active" and c.buyer_name][:8]
    return PublicCampaignOut(**out.model_dump(), supporters=[c.buyer_name.split()[0] for c in recent])


class CardIn(BaseModel):
    amount: Money = Field(ge=reopen.CARD_MIN, le=reopen.CARD_MAX)
    buyer_name: str | None = Field(default=None, max_length=120)
    payment_method: Literal["paypal", "venmo", "paylater"] = "paypal"


class CardCreated(BaseModel):
    card_id: int
    order_id: str


@router.post("/reopen/{slug}/cards", response_model=CardCreated, status_code=201)
def start_card(slug: str, body: CardIn, buyer: OptionalUser, db: DB) -> CardCreated:
    b = business_by_slug(db, slug)
    campaign = reopen.current_campaign(b)
    if campaign is None:
        raise HTTPException(409, "This Reopen Fund isn't selling cards right now")
    card = run(reopen.start_card, db, campaign, body.amount, body.buyer_name, buyer, body.payment_method)
    try:
        card.paypal_order_id = orders.create_order(
            amount=body.amount,
            description=f"Hearthline Reopen Fund: {b.name} gift card",
            custom_id=f"{reopen.CUSTOM_ID_PREFIX}{card.id}",
            reference_id=f"reopen-{campaign.id}",
        )
    except ErrorException as e:
        db.rollback()
        raise HTTPException(502, f"PayPal couldn't start the payment: {paypal_reason(e)}") from None
    db.commit()
    return CardCreated(card_id=card.id, order_id=card.paypal_order_id)


@router.post("/gift-cards/{card_id}/capture", response_model=CardOut)
def capture_card(card_id: int, db: DB) -> CardOut:
    """Called after the buyer approves in the PayPal/Venmo window. Returns the card with its code."""
    card = db.get(GiftCard, card_id)
    if card is None or card.paypal_order_id is None:
        raise HTTPException(404, "Gift card not found")
    if card.status == "pending":
        try:
            capture = orders.capture_order(card.paypal_order_id)
        except ErrorException as e:
            card.status = "failed"
            db.commit()
            raise HTTPException(402, f"PayPal didn't complete the payment: {paypal_reason(e)}") from None
        reopen.activate(db, card, capture)
        if capture.status != "COMPLETED":
            raise HTTPException(402, f"Payment is {capture.status.lower()}; the card activates when PayPal confirms it")
    return card_out(card)


class RegularIn(BaseModel):
    buyer_name: str | None = Field(default=None, max_length=120)


class RegularStarted(BaseModel):
    regular_id: int
    approval_url: str | None


class RegularOut(BaseModel):
    id: int
    status: str
    payments: int
    card: CardOut


@router.post("/reopen/{slug}/regulars", response_model=RegularStarted, status_code=201)
def become_regular(slug: str, body: RegularIn, buyer: OptionalUser, db: DB) -> RegularStarted:
    """Monthly pre-payment through a PayPal subscription; the person approves it at `approval_url`."""
    b = business_by_slug(db, slug)
    campaign = reopen.current_campaign(b)
    if campaign is None:
        raise HTTPException(409, "This Reopen Fund is not taking new regulars right now")
    regular, link = run(reopen.start_regular, db, campaign, body.buyer_name, buyer, f"{get_settings().web_url}/paid")
    return RegularStarted(regular_id=regular.id, approval_url=link)


@router.post("/regulars/{regular_id}/sync", response_model=RegularOut)
def sync_regular(regular_id: int, db: DB) -> RegularOut:
    """After approval (PayPal's return page) or any time: the subscription's status and payments so far."""
    regular = db.get(ReopenRegular, regular_id)
    if regular is None:
        raise HTTPException(404, "Not found")
    run(reopen.sync_regular, db, regular)
    return RegularOut(
        id=regular.id, status=regular.status, payments=len(regular.card.payments), card=card_out(regular.card)
    )


@router.get("/gift-cards/{code}", response_model=CardOut)
def view_card(code: str, db: DB) -> CardOut:
    """Public to whoever holds the code (it's printed on the card as a QR code)."""
    card = db.scalar(select(GiftCard).where(GiftCard.code == reopen.normalize_code(code)))
    if card is None or card.status in {"pending", "failed"}:
        raise HTTPException(404, "Gift card not found")
    return card_out(card)


# --- The business owner ------------------------------------------------------------------------------


def my_business(owner: Owner, db: DB) -> Business:
    b = db.scalar(select(Business).where(Business.owner_user_id == owner.id))
    if b is None:
        raise HTTPException(404, "No business for this account")
    return b


MyBusiness = Annotated[Business, Depends(my_business)]


def my_campaign(b: Business) -> ReopenCampaign:
    campaign = reopen.current_campaign(b)
    if campaign is None:
        raise HTTPException(404, "No Reopen Fund running")
    return campaign


class TrancheIn(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    amount: Money = Field(gt=0)
    start_date: datetime
    end_date: datetime


class CampaignIn(BaseModel):
    bonus_percent: int = Field(ge=0, le=reopen.MAX_BONUS_PERCENT)
    reopen_by: datetime
    tranches: list[TrancheIn] = Field(min_length=1, max_length=12)


class NoteIn(BaseModel):
    note: str = Field(default="", max_length=500)


class RedeemIn(BaseModel):
    code: str = Field(min_length=4, max_length=40)
    amount: Money = Field(gt=0)


@router.get("/business/me", response_model=BusinessOut)
def get_my_business(b: MyBusiness, db: DB) -> BusinessOut:
    return business_out(db, b)


@router.post("/business/me/campaign", response_model=BusinessOut, status_code=201)
def create_my_campaign(body: CampaignIn, b: MyBusiness, owner: Owner, db: DB) -> BusinessOut:
    run(
        reopen.create_campaign,
        db,
        b,
        bonus_percent=body.bonus_percent,
        reopen_by=body.reopen_by,
        tranches=[t.model_dump() for t in body.tranches],
        actor=owner,
    )
    return business_out(db, b)


@router.post("/business/me/tranches/{tranche_id}/request", response_model=BusinessOut)
def request_tranche(tranche_id: int, body: NoteIn, b: MyBusiness, owner: Owner, db: DB) -> BusinessOut:
    tranche = db.get(ReopenTranche, tranche_id)
    if tranche is None or tranche.campaign.business_id != b.id:
        raise HTTPException(404, "Step not found")
    run(reopen.request_tranche, db, tranche, owner, body.note)
    return business_out(db, b)


@router.post("/business/me/reopened", response_model=BusinessOut)
def reopened(b: MyBusiness, owner: Owner, db: DB) -> BusinessOut:
    run(reopen.mark_reopened, db, my_campaign(b), owner)
    return business_out(db, b)


@router.get("/business/me/cards", response_model=list[CardRow])
def my_cards(b: MyBusiness, db: DB) -> list[CardRow]:
    campaign = reopen.current_campaign(b) or (b.campaigns[-1] if b.campaigns else None)
    if campaign is None:
        return []
    return [
        CardRow(
            id=c.id,
            code_end=c.code[-4:],
            buyer=c.buyer_name.split()[0] if c.buyer_name else None,
            amount_paid=c.amount_paid,
            face_value=c.face_value,
            balance=c.balance,
            status=c.status,
            payment_method=c.payment_method,
            activated_at=c.activated_at,
        )
        for c in campaign.cards
        if c.status not in {"pending", "failed"}
    ]


@router.get("/business/me/cards/{code}", response_model=CardOut)
def look_up_card(code: str, b: MyBusiness, db: DB) -> CardOut:
    card = db.scalar(select(GiftCard).where(GiftCard.code == reopen.normalize_code(code)))
    if card is None or card.status in {"pending", "failed"} or card.campaign.business_id != b.id:
        raise HTTPException(404, "No gift card for your business with that code")
    return card_out(card)


@router.post("/business/me/redeem", response_model=CardOut)
def redeem(body: RedeemIn, b: MyBusiness, owner: Owner, db: DB) -> CardOut:
    return card_out(run(reopen.redeem, db, b, body.code, body.amount, owner))


# --- Staff: verify businesses, release money, run the deadline check ---------------------------------


class StaffBusinessOut(BusinessOut):
    owner_name: str
    license_number: str
    address: str
    payout_email: str | None


class DecideIn(BaseModel):
    approve: bool
    note: str = Field(default="", max_length=500)


@router.get("/command/businesses", response_model=list[StaffBusinessOut])
def list_businesses(staff: OrgStaff, db: DB) -> list[StaffBusinessOut]:
    out = []
    for b in db.scalars(select(Business).order_by(Business.id)):
        out.append(
            StaffBusinessOut(
                **business_out(db, b).model_dump(),
                owner_name=b.owner.name,
                license_number=b.license_number,
                address=f"{b.address_line}, {b.city}, {b.state}",
                payout_email=b.payout_email,
            )
        )
    return out


@router.post("/command/businesses/{business_id}/verify", response_model=BusinessOut)
def verify(business_id: int, body: DecideIn, staff: OrgStaff, db: DB) -> BusinessOut:
    b = db.get(Business, business_id)
    if b is None:
        raise HTTPException(404, "Business not found")
    return business_out(db, run(reopen.verify_business, db, b, staff, body.approve, body.note))


@router.post("/command/tranches/{tranche_id}/decide", response_model=TrancheOut)
def decide(tranche_id: int, body: DecideIn, staff: OrgStaff, db: DB) -> TrancheOut:
    tranche = db.get(ReopenTranche, tranche_id)
    if tranche is None:
        raise HTTPException(404, "Step not found")
    return TrancheOut.model_validate(
        run(reopen.decide_tranche, db, tranche, staff, body.approve, body.note), from_attributes=True
    )


@router.post("/command/reopen/deadlines")
def deadlines(staff: OrgStaff, db: DB) -> dict:
    return {"refunded_campaigns": reopen.run_deadlines(db, staff)}


# --- Reopening plan for Bryntum Gantt -----------------------------------------------------------------

TRANCHE_COLOR = {"pending": "gray", "requested": "orange", "released": "green", "rejected": "red"}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@router.get("/bryntum/reopen/{slug}/load")
def gantt_load(slug: str, db: DB, requestId: int | None = None, data: str | None = None) -> dict:  # noqa: N803
    """Public, like the campaign page: what the money pays for and when."""
    if requestId is None and data:
        try:
            requestId = json.loads(data).get("requestId")  # noqa: N806
        except (ValueError, AttributeError):
            pass
    b = business_by_slug(db, slug)
    campaign = b.campaigns[-1]
    children = [
        {
            "id": t.id,
            "name": f"{t.seq}. {t.title} · ${t.amount:,.0f}",
            "startDate": _aware(t.start_date).isoformat(),
            "endDate": _aware(t.end_date).isoformat(),
            "manuallyScheduled": True,
            "percentDone": 100 if t.status == "released" else 50 if t.status == "requested" else 0,
            "eventColor": TRANCHE_COLOR.get(t.status, "blue"),
            "status": t.status,
        }
        for t in campaign.tranches
    ]
    reopening = {
        "id": "reopen",
        "name": "Reopening day",
        "startDate": _aware(campaign.reopened_at or campaign.reopen_by).isoformat(),
        "duration": 0,  # a milestone diamond
        "manuallyScheduled": True,
        "status": "milestone",
    }
    deps = [
        {"id": i, "fromTask": a["id"], "toTask": b_["id"], "type": 2}
        for i, (a, b_) in enumerate(zip(children, [*children[1:], reopening], strict=False), start=1)
    ]
    return {
        "success": True,
        "requestId": requestId,
        "tasks": {
            "rows": [
                {"id": f"campaign-{campaign.id}", "name": b.name, "expanded": True, "children": [*children, reopening]}
            ]
        },
        "dependencies": {"rows": deps},
    }


@router.post("/bryntum/reopen/{slug}/sync")
def gantt_sync(slug: str, owner: Owner, db: DB, payload: Annotated[dict, Body()]) -> dict:
    """Only the owner, and only steps that haven't been paid out, can move."""
    request_id = payload.get("requestId")
    b = business_by_slug(db, slug)
    if b.owner_user_id != owner.id:
        return {"success": False, "requestId": request_id, "message": "Only the owner can change the plan."}
    tasks = payload.get("tasks") or {}
    if tasks.get("added") or tasks.get("removed"):
        return {"success": False, "requestId": request_id, "message": "Change the steps in the plan, not the chart."}
    by_id = {t.id: t for t in b.campaigns[-1].tranches}
    changed = []
    for row in tasks.get("updated", []):
        t = by_id.get(row.get("id"))
        if t is None or t.status == "released" or not ({"startDate", "endDate"} & row.keys()):
            continue
        length = _aware(t.end_date) - _aware(t.start_date)
        if "startDate" in row:
            t.start_date = _aware(datetime.fromisoformat(row["startDate"]))
        t.end_date = _aware(datetime.fromisoformat(row["endDate"])) if "endDate" in row else t.start_date + length
        if t.end_date < t.start_date:
            db.rollback()
            return {"success": False, "requestId": request_id, "message": "A step can't end before it starts."}
        audit.record(
            db,
            actor_user_id=owner.id,
            action="reopen.tranche_rescheduled",
            subject_type="reopen_tranche",
            subject_id=t.id,
            data={"start": t.start_date.isoformat(), "end": t.end_date.isoformat()},
        )
        changed.append({"id": t.id})
    db.commit()
    return {"success": True, "requestId": request_id, "tasks": {"rows": changed}}
