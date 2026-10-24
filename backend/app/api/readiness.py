"""The readiness fund: what it holds (public), and a donor's monthly gift through PayPal Subscriptions."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import readiness
from app.auth import require_role
from app.config import get_settings
from app.db import get_db
from app.models import ReadinessGiver, Role, User
from app.schemas import Money

router = APIRouter(tags=["readiness"])
DB = Annotated[Session, Depends(get_db)]
Donor = Annotated[User, Depends(require_role(Role.DONOR))]


class PoolOut(BaseModel):
    balance: Money
    givers: int
    monthly: Money
    released: Money
    batches: int
    tiers: list[Money]


class GiverOut(BaseModel):
    id: int
    monthly: Money
    status: str
    created_at: datetime
    activated_at: datetime | None
    given: Money
    payments: int


class MineOut(BaseModel):
    pool: PoolOut
    mine: GiverOut | None


class StartIn(BaseModel):
    monthly: Decimal


class StartOut(BaseModel):
    giver: GiverOut
    approval_url: str | None


def pool_out(db: Session) -> PoolOut:
    p = readiness.pool(db)
    return PoolOut(
        balance=p.balance,
        givers=p.givers,
        monthly=p.monthly,
        released=p.released,
        batches=p.batches,
        tiers=list(readiness.TIERS),
    )


def giver_out(g: ReadinessGiver) -> GiverOut:
    return GiverOut(
        id=g.id,
        monthly=g.monthly,
        status=g.status,
        created_at=g.created_at,
        activated_at=g.activated_at,
        given=sum((p.amount for p in g.payments), Decimal(0)),
        payments=len(g.payments),
    )


def _mine(db: Session, donor: User, giver_id: int) -> ReadinessGiver:
    giver = db.get(ReadinessGiver, giver_id)
    if giver is None or giver.user_id != donor.id:
        raise HTTPException(404, "Monthly gift not found")
    return giver


@router.get("/readiness", response_model=PoolOut)
def public_pool(db: DB) -> PoolOut:
    """What the readiness fund holds now, and what it has paid families."""
    return pool_out(db)


@router.get("/donors/me/readiness", response_model=MineOut)
def mine(donor: Donor, db: DB) -> MineOut:
    latest = db.scalar(
        select(ReadinessGiver)
        .where(ReadinessGiver.user_id == donor.id, ReadinessGiver.status.in_(("active", "pending")))
        .order_by(ReadinessGiver.id.desc())
    )
    return MineOut(pool=pool_out(db), mine=giver_out(latest) if latest else None)


@router.post("/donors/me/readiness", response_model=StartOut, status_code=201)
def start(body: StartIn, donor: Donor, db: DB) -> StartOut:
    try:
        giver, url = readiness.start(db, donor, body.monthly, f"{get_settings().web_url}/giving/readiness")
    except readiness.ReadinessError as e:
        raise HTTPException(409, str(e)) from None
    return StartOut(giver=giver_out(giver), approval_url=url)


@router.post("/donors/me/readiness/{giver_id}/finish", response_model=MineOut)
def finish(giver_id: int, donor: Donor, db: DB) -> MineOut:
    """Back from PayPal: record where the subscription stands, and any payment PayPal already took."""
    try:
        readiness.sync(db, _mine(db, donor, giver_id))
    except readiness.ReadinessError as e:
        raise HTTPException(502, str(e)) from None
    return mine(donor, db)


@router.post("/donors/me/readiness/{giver_id}/stop", response_model=MineOut)
def stop(giver_id: int, donor: Donor, db: DB) -> MineOut:
    try:
        readiness.stop(db, _mine(db, donor, giver_id), donor)
    except readiness.ReadinessError as e:
        raise HTTPException(409, str(e)) from None
    return mine(donor, db)
