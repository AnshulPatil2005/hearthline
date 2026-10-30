"""The dispatch agent for the relief organization: plan a day of crew visits, then accept or reject each proposal."""

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import dispatch
from app.auth import require_role
from app.db import get_db
from app.models import DispatchPlan, DispatchProposal, Role, User

router = APIRouter(prefix="/command/dispatch", tags=["dispatch"])
DB = Annotated[Session, Depends(get_db)]
Dispatcher = Annotated[User, Depends(require_role(Role.ORG_ADMIN, Role.SUPERVISOR))]


class ProposalOut(BaseModel):
    id: int
    job_id: int
    job: str
    kind: str
    household: str
    street: str | None
    crew_id: int | None
    crew: str | None
    starts_at: datetime | None
    ends_at: datetime | None
    travel_minutes: int
    rank: int
    urgency: int
    reason: str
    status: str  # proposed | accepted | rejected | skipped | stale


class PlanOut(BaseModel):
    id: int
    day: date
    instructions: str
    summary: str
    by_ai: bool
    created_at: datetime
    proposals: list[ProposalOut]
    counts: dict[str, int]


class PlanIn(BaseModel):
    day: date | None = None  # default: tomorrow, on Sablewood's clock
    instructions: str = Field(default="", max_length=500)


def plan_out(p: DispatchPlan) -> PlanOut:
    counts: dict[str, int] = {}
    for pr in p.proposals:
        counts[pr.status] = counts.get(pr.status, 0) + 1
    return PlanOut(
        id=p.id,
        day=p.day,
        instructions=p.instructions,
        summary=p.summary,
        by_ai=p.by_ai,
        created_at=p.created_at,
        counts=counts,
        proposals=[
            ProposalOut(
                id=pr.id,
                job_id=pr.job_id,
                job=pr.job.title,
                kind=pr.job.kind,
                household=pr.job.household.name,
                street=pr.job.household.street,
                crew_id=pr.crew_id,
                crew=pr.crew.name if pr.crew else None,
                starts_at=pr.starts_at,
                ends_at=pr.ends_at,
                travel_minutes=pr.travel_minutes,
                rank=pr.rank,
                urgency=pr.urgency,
                reason=pr.reason,
                status=pr.status,
            )
            for pr in p.proposals
        ],
    )


def _proposal(db: Session, proposal_id: int) -> DispatchProposal:
    proposal = db.get(DispatchProposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    return proposal


@router.get("/plan", response_model=PlanOut | None)
def latest_plan(staff: Dispatcher, db: DB) -> PlanOut | None:
    p = dispatch.latest(db)
    return plan_out(p) if p else None


@router.post("/plan", response_model=PlanOut, status_code=201)
def make_plan(body: PlanIn, staff: Dispatcher, db: DB) -> PlanOut:
    """The agent plans the day (one AI call); nothing moves until someone accepts."""
    day = body.day or (datetime.now(dispatch.SITE) + timedelta(days=1)).date()
    try:
        return plan_out(dispatch.plan(db, staff, day, body.instructions.strip()))
    except dispatch.DispatchError as e:
        raise HTTPException(409, str(e)) from None


@router.post("/proposals/{proposal_id}/accept", response_model=PlanOut)
def accept(proposal_id: int, staff: Dispatcher, db: DB) -> PlanOut:
    proposal = _proposal(db, proposal_id)
    try:
        dispatch.accept(db, proposal, staff)
    except dispatch.DispatchError as e:
        raise HTTPException(409, str(e)) from None
    return plan_out(proposal.plan)


@router.post("/proposals/{proposal_id}/reject", response_model=PlanOut)
def reject(proposal_id: int, staff: Dispatcher, db: DB) -> PlanOut:
    proposal = _proposal(db, proposal_id)
    try:
        dispatch.reject(db, proposal, staff)
    except dispatch.DispatchError as e:
        raise HTTPException(409, str(e)) from None
    return plan_out(proposal.plan)


@router.post("/plans/{plan_id}/accept-all", response_model=PlanOut)
def accept_all(plan_id: int, staff: Dispatcher, db: DB) -> PlanOut:
    p = db.get(DispatchPlan, plan_id)
    if p is None:
        raise HTTPException(404, "Plan not found")
    dispatch.accept_all(db, p, staff)
    db.refresh(p)
    return plan_out(p)
