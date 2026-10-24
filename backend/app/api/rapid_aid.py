"""First-72-hours aid for the relief organization: official warnings for a disaster's zone, who would be paid, who
Sentinel holds back, and one person's approval that pays them through PayPal Payouts."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import rapid_aid, readiness
from app.auth import require_role
from app.db import get_db
from app.models import DisasterEvent, RapidAidTrigger, Role, User
from app.schemas import Money

router = APIRouter(prefix="/command/rapid-aid", tags=["rapid-aid"])
DB = Annotated[Session, Depends(get_db)]
OrgStaff = Annotated[User, Depends(require_role(Role.ORG_ADMIN, Role.SUPERVISOR))]


class HeldOut(BaseModel):
    household_id: int
    name: str
    reason: str


class BatchOut(BaseModel):
    id: int
    status: str  # sent | failed | ...
    households: int
    total: Money
    paypal_batch_id: str | None
    error: str | None


class TriggerOut(BaseModel):
    id: int
    disaster: str
    source: str  # nws | declaration | simulated
    event: str
    headline: str
    severity: str
    issued_at: datetime
    status: str  # proposed | approved | dismissed
    decided_by: str | None
    decided_at: datetime | None
    note: str | None
    households: int  # who would be paid now (proposed) or was paid (approved)
    total: Money
    readiness_covers: Money  # what the readiness fund would pay (proposed) or paid (approved)
    held: list[HeldOut]
    left_out: dict[str, int]
    batch: BatchOut | None


class DisasterOut(BaseModel):
    id: int
    name: str


class ReadinessOut(BaseModel):
    balance: Money
    givers: int
    monthly: Money


class Board(BaseModel):
    disasters: list[DisasterOut]
    triggers: list[TriggerOut]
    readiness: ReadinessOut
    base: Money
    per_person: Money
    cap: Money


class DisasterIn(BaseModel):
    disaster_id: int


class DismissIn(BaseModel):
    note: str = Field(min_length=3, max_length=500)


def _trigger(db: Session, t: RapidAidTrigger) -> TriggerOut:
    held: list[HeldOut] = []
    left_out: dict[str, int] = {}
    batch = None
    if t.status == "proposed":
        paid, held_, counts = rapid_aid.plan(db, t)
        households, total = len(paid), sum((p.amount for p in paid), Decimal(0))
        held, left_out = (
            [HeldOut(household_id=h.household_id, name=h.name, reason=h.reason) for h in held_],
            dict(counts),
        )
    elif t.batch is not None:
        sent = [i for i in t.batch.items if i.status not in ("queued", "skipped")]
        households, total = len(sent), t.batch.total_amount
        batch = BatchOut(
            id=t.batch.id,
            status=t.batch.status,
            households=len(sent),
            total=t.batch.total_amount,
            paypal_batch_id=t.batch.paypal_batch_id,
            error=t.batch.error,
        )
        held = [HeldOut(**h) for h in t.batch.rule.get("held_for_review", [])]
    else:
        households, total = 0, Decimal(0)
    if t.status == "proposed":
        covers = readiness.covers(db, total)
    else:
        covers = Decimal(t.batch.rule.get("readiness_covered", "0")) if t.batch else Decimal(0)
    return TriggerOut(
        id=t.id,
        disaster=t.disaster.name,
        source=t.source,
        event=t.event,
        headline=t.headline,
        severity=t.severity,
        issued_at=t.issued_at,
        status=t.status,
        decided_by=db.get(User, t.decided_by_user_id).name if t.decided_by_user_id else None,
        decided_at=t.decided_at,
        note=t.note,
        households=households,
        total=total,
        readiness_covers=covers,
        held=held,
        left_out=left_out,
        batch=batch,
    )


def _board(db: Session) -> Board:
    disasters = list(
        db.scalars(select(DisasterEvent).where(DisasterEvent.status == "active").order_by(DisasterEvent.id))
    )
    triggers = db.scalars(select(RapidAidTrigger).order_by(RapidAidTrigger.id.desc()).limit(20))
    pool = readiness.pool(db)
    return Board(
        disasters=[DisasterOut(id=d.id, name=d.name) for d in disasters],
        triggers=[_trigger(db, t) for t in triggers],
        readiness=ReadinessOut(balance=pool.balance, givers=pool.givers, monthly=pool.monthly),
        base=rapid_aid.BASE,
        per_person=rapid_aid.PER_PERSON,
        cap=rapid_aid.CAP,
    )


def _event(db: Session, disaster_id: int) -> DisasterEvent:
    event = db.get(DisasterEvent, disaster_id)
    if event is None or event.status != "active":
        raise HTTPException(404, "No active disaster with that id")
    return event


def _one(db: Session, trigger_id: int) -> RapidAidTrigger:
    trigger = db.get(RapidAidTrigger, trigger_id)
    if trigger is None:
        raise HTTPException(404, "Trigger not found")
    return trigger


@router.get("", response_model=Board)
def board(_staff: OrgStaff, db: DB) -> Board:
    return _board(db)


@router.post("/check", response_model=Board)
def check(body: DisasterIn, _staff: OrgStaff, db: DB) -> Board:
    """Ask the National Weather Service for active warnings at the disaster's zone."""
    try:
        rapid_aid.check_official(db, _event(db, body.disaster_id))
    except rapid_aid.RapidAidError as e:
        raise HTTPException(503, str(e)) from None
    return _board(db)


@router.post("/simulate", response_model=Board)
def simulate(body: DisasterIn, _staff: OrgStaff, db: DB) -> Board:
    """A simulated evacuation order, so the flow can be shown on any day."""
    try:
        rapid_aid.simulate(db, _event(db, body.disaster_id))
    except rapid_aid.RapidAidError as e:
        raise HTTPException(409, str(e)) from None
    return _board(db)


@router.post("/{trigger_id}/approve", response_model=Board)
def approve(trigger_id: int, staff: OrgStaff, db: DB) -> Board:
    try:
        rapid_aid.approve(db, _one(db, trigger_id), staff)
    except rapid_aid.RapidAidError as e:
        raise HTTPException(409, str(e)) from None
    return _board(db)


@router.post("/{trigger_id}/dismiss", response_model=Board)
def dismiss(trigger_id: int, body: DismissIn, staff: OrgStaff, db: DB) -> Board:
    try:
        rapid_aid.dismiss(db, _one(db, trigger_id), staff, body.note)
    except rapid_aid.RapidAidError as e:
        raise HTTPException(409, str(e)) from None
    return _board(db)
