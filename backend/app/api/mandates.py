"""A donor's giving mandates: save a PayPal account once, set limits, and let the giving agent give within them."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import mandates
from app.auth import require_role
from app.config import get_settings
from app.db import get_db
from app.models import GivingMandate, MandateGift, Role, User
from app.schemas import Money

router = APIRouter(prefix="/donors/me/mandates", tags=["giving-mandates"])
DB = Annotated[Session, Depends(get_db)]
Donor = Annotated[User, Depends(require_role(Role.DONOR))]


class GiftOut(BaseModel):
    id: int
    item: str
    family: str
    registry_slug: str
    amount: Money
    reason: str
    by_ai: bool
    status: str  # claimed | given | failed | checking
    error: str | None
    created_at: datetime
    given_at: datetime | None


class MandateOut(BaseModel):
    id: int
    status: str  # pending | saving | active | paused | revoked
    states: list[str]
    categories: list[str]
    per_gift_max: Money
    monthly_max: Money
    note: str
    paypal_email: str | None
    error: str | None
    given_this_month: Money
    left_this_month: Money
    created_at: datetime
    activated_at: datetime | None
    revoked_at: datetime | None
    last_run_at: datetime | None
    gifts: list[GiftOut]


class Options(BaseModel):
    states: list[str]
    categories: list[str]
    max_per_gift: Money
    max_monthly: Money


class MandateIn(BaseModel):
    states: list[str] = Field(default_factory=list, max_length=60)
    categories: list[str] = Field(default_factory=list, max_length=30)
    per_gift_max: Decimal = Field(gt=0)
    monthly_max: Decimal = Field(gt=0)
    note: str = Field(default="", max_length=280)


class Started(BaseModel):
    mandate: MandateOut
    approve_url: str  # PayPal's page where the donor saves their account


class FinishIn(BaseModel):
    setup_id: str = Field(min_length=4, max_length=64)  # PayPal's approval_token_id on the return URL


class RoundOut(BaseModel):
    mandate: MandateOut
    summary: str
    by_ai: bool
    given: int


def _gift(g: MandateGift) -> GiftOut:
    reg = g.item.rebuild_registry
    return GiftOut(
        id=g.id,
        item=g.item.name,
        family=reg.household.name,
        registry_slug=reg.slug,
        amount=g.amount,
        reason=g.reason,
        by_ai=g.by_ai,
        status=g.status,
        error=g.error,
        created_at=g.created_at,
        given_at=g.given_at,
    )


def _out(db: Session, m: GivingMandate) -> MandateOut:
    return MandateOut(
        id=m.id,
        status=m.status,
        states=m.states,
        categories=m.categories,
        per_gift_max=m.per_gift_max,
        monthly_max=m.monthly_max,
        note=m.note,
        paypal_email=m.paypal_email,
        error=m.error,
        given_this_month=mandates.given_this_month(db, m),
        left_this_month=mandates.left_this_month(db, m),
        created_at=m.created_at,
        activated_at=m.activated_at,
        revoked_at=m.revoked_at,
        last_run_at=m.last_run_at,
        gifts=[_gift(g) for g in m.gifts],
    )


def _mine(db: Session, donor: User, mandate_id: int) -> GivingMandate:
    m = db.get(GivingMandate, mandate_id)
    if m is None or m.donor_user_id != donor.id:
        raise HTTPException(404, "Giving mandate not found")
    return m


def _run[T](fn: Callable[..., T], *args: object) -> T:
    try:
        return fn(*args)
    except mandates.MandateError as e:
        raise HTTPException(e.status_code, str(e)) from None


@router.get("/options", response_model=Options)
def options(_donor: Donor) -> Options:
    return Options(
        states=mandates.STATES,
        categories=mandates.CATEGORIES,
        max_per_gift=mandates.MAX_PER_GIFT,
        max_monthly=mandates.MAX_MONTHLY,
    )


@router.get("", response_model=list[MandateOut])
def my_mandates(donor: Donor, db: DB) -> list[MandateOut]:
    rows = db.scalars(
        select(GivingMandate).where(GivingMandate.donor_user_id == donor.id).order_by(GivingMandate.id.desc())
    )
    return [_out(db, m) for m in rows]


@router.post("", response_model=Started, status_code=201)
def create_mandate(body: MandateIn, donor: Donor, db: DB) -> Started:
    try:
        m, approve_url = mandates.create(
            db,
            donor,
            states=body.states,
            categories=body.categories,
            per_gift_max=body.per_gift_max,
            monthly_max=body.monthly_max,
            note=body.note,
            web_url=get_settings().web_url,
        )
    except mandates.MandateError as e:
        raise HTTPException(e.status_code, str(e)) from None
    return Started(mandate=_out(db, m), approve_url=approve_url)


@router.post("/finish", response_model=MandateOut)
def finish_mandate(body: FinishIn, donor: Donor, db: DB) -> MandateOut:
    return _out(db, _run(mandates.finish, db, donor, body.setup_id))


@router.post("/{mandate_id}/pause", response_model=MandateOut)
def pause_mandate(mandate_id: int, donor: Donor, db: DB) -> MandateOut:
    return _out(db, _run(mandates.pause, db, _mine(db, donor, mandate_id)))


@router.post("/{mandate_id}/resume", response_model=MandateOut)
def resume_mandate(mandate_id: int, donor: Donor, db: DB) -> MandateOut:
    return _out(db, _run(mandates.resume, db, _mine(db, donor, mandate_id)))


@router.post("/{mandate_id}/revoke", response_model=MandateOut)
def revoke_mandate(mandate_id: int, donor: Donor, db: DB) -> MandateOut:
    return _out(db, _run(mandates.revoke, db, _mine(db, donor, mandate_id)))


@router.post("/{mandate_id}/run", response_model=RoundOut)
def run_mandate(mandate_id: int, donor: Donor, db: DB) -> RoundOut:
    """Give now, within the limits (the same round a new disaster or a newly verified family starts)."""
    m = _mine(db, donor, mandate_id)
    result = _run(mandates.run, db, m)
    db.refresh(m)
    return RoundOut(
        mandate=_out(db, m),
        summary=result.summary,
        by_ai=result.by_ai,
        given=sum(1 for g in result.gifts if g.status == "given"),
    )
