"""Payment disputes desk for relief-organization staff: see what our records show, edit the draft, decide.
Also "Ask PayPal": the Funds agent reads PayPal through PayPal's MCP server."""

import logging
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, dispute_pdf, disputes
from app.agents import paypal_desk
from app.auth import require_role
from app.db import get_db
from app.models import PaymentDispute, Role, User
from app.schemas import Money

log = logging.getLogger(__name__)
router = APIRouter(prefix="/command/disputes", tags=["disputes"])
DB = Annotated[Session, Depends(get_db)]
OrgStaff = Annotated[User, Depends(require_role(Role.ORG_ADMIN, Role.SUPERVISOR))]


class DisputeRow(BaseModel):
    id: int
    paypal_dispute_id: str
    reason: str
    reason_text: str
    status: str
    stage: str
    amount: Money
    subject: str
    kind: Literal["donation", "gift_card", "unmatched"]
    respond_by: datetime | None
    recommendation: str | None
    decision: str | None
    created_at: datetime
    demo: bool


class Fact(BaseModel):
    label: str
    value: str


class Event(BaseModel):
    at: datetime
    what: str


class DisputeDetail(DisputeRow):
    payer_message: str
    outcome: str | None
    actions: list[str]
    facts: list[Fact]
    timeline: list[Event]
    evidence_type: str
    tracking: list[dict]
    recommended: str
    because: str
    draft: str | None
    draft_by_ai: bool
    decided_by: str | None
    decided_at: datetime | None


def _row(d: PaymentDispute, rec: disputes.Records) -> dict:
    return {
        "id": d.id,
        "paypal_dispute_id": d.paypal_dispute_id,
        "reason": d.reason,
        "reason_text": disputes.REASONS.get(d.reason, d.reason),
        "status": d.status,
        "stage": d.stage,
        "amount": d.amount,
        "subject": rec.subject,
        "kind": "donation" if d.donation_id else "gift_card" if d.gift_card_id else "unmatched",
        "respond_by": d.respond_by,
        "recommendation": d.recommendation or rec.recommendation,
        "decision": d.decision,
        "created_at": d.created_at,
        "demo": disputes.is_demo(d),
    }


def _get(db: Session, dispute_id: int) -> PaymentDispute:
    d = db.get(PaymentDispute, dispute_id)
    if d is None:
        raise HTTPException(404, "Not found")
    return d


def _detail(db: Session, d: PaymentDispute) -> DisputeDetail:
    rec = disputes.records(db, d)
    decider = db.get(User, d.decided_by_user_id) if d.decided_by_user_id else None
    return DisputeDetail(
        **_row(d, rec),
        payer_message=d.payer_message,
        outcome=d.outcome,
        actions=d.actions,
        facts=[Fact(label=label, value=value) for label, value in rec.facts],
        timeline=[Event(at=at, what=what) for at, what in rec.timeline],
        evidence_type=rec.evidence_type,
        tracking=rec.tracking,
        recommended=rec.recommendation,
        because=rec.because,
        draft=d.draft,
        draft_by_ai=d.draft_by_ai,
        decided_by=decider.name if decider else None,
        decided_at=d.decided_at,
    )


@router.get("", response_model=list[DisputeRow])
def list_disputes(staff: OrgStaff, db: DB) -> list[dict]:
    found = db.scalars(select(PaymentDispute).order_by(PaymentDispute.created_at.desc()))
    return [_row(d, disputes.records(db, d)) for d in found]


class Synced(BaseModel):
    seen: int


@router.post("/sync", response_model=Synced)
def sync(staff: OrgStaff, db: DB) -> Synced:
    """Pull disputes from PayPal now (webhooks normally deliver them)."""
    try:
        return Synced(seen=disputes.sync(db))
    except disputes.DisputeError as e:
        raise HTTPException(502, str(e)) from e


@router.get("/{dispute_id}", response_model=DisputeDetail)
def get_dispute(dispute_id: int, staff: OrgStaff, db: DB) -> DisputeDetail:
    return _detail(db, _get(db, dispute_id))


@router.post("/{dispute_id}/draft", response_model=DisputeDetail)
def make_draft(dispute_id: int, staff: OrgStaff, db: DB, again: bool = False) -> DisputeDetail:
    """The Funds agent drafts the response (slow: an AI call). `again` replaces an existing draft."""
    d = _get(db, dispute_id)
    if d.decision in {"evidence_sent", "refunded"}:
        raise HTTPException(409, "This dispute has already been answered")
    return _detail(db, disputes.draft(db, d, force=again))


class Decision(BaseModel):
    action: Literal["message", "evidence", "refund"]
    note: str = Field(max_length=2000)


@router.post("/{dispute_id}/respond", response_model=DisputeDetail)
def respond(dispute_id: int, body: Decision, staff: OrgStaff, db: DB) -> DisputeDetail:
    d = _get(db, dispute_id)
    try:
        disputes.respond(db, d, body.action, body.note, staff)
    except disputes.DisputeError as e:
        raise HTTPException(409, str(e)) from e
    return _detail(db, d)


@router.get("/{dispute_id}/evidence.pdf")
def evidence_pdf(dispute_id: int, staff: OrgStaff, db: DB) -> Response:
    """The records PDF that goes to PayPal with evidence, for staff to check first."""
    d = _get(db, dispute_id)
    rec = disputes.records(db, d)
    pdf = dispute_pdf.build(d, rec, d.draft or rec.because)
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="hearthline-{d.paypal_dispute_id}.pdf"'},
    )


paypal_router = APIRouter(prefix="/command/paypal", tags=["disputes"])


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=500)


class AgentStep(BaseModel):
    tool: str
    source: Literal["paypal", "hearthline"]
    args: dict
    ok: bool
    summary: str


class PayPalAnswer(BaseModel):
    answer: str
    steps: list[AgentStep]


@paypal_router.post("/ask", response_model=PayPalAnswer)
def ask_paypal(body: Question, staff: OrgStaff, db: DB) -> PayPalAnswer:
    """The Funds agent answers with PayPal's own MCP tools (read-only) and Hearthline's records."""
    if not ai.configured():
        raise HTTPException(503, "No AI model is configured")
    try:
        result = paypal_desk.ask(db, body.question, staff)
    except ai.AIError as e:
        raise HTTPException(503, "The AI models are busy right now. Try again in a minute.") from e
    except Exception as e:  # PayPal's MCP server unreachable or failing
        log.exception("Ask PayPal failed")
        raise HTTPException(502, "Couldn't reach PayPal's MCP server. Try again in a minute.") from e
    return PayPalAnswer(answer=result.answer, steps=[AgentStep(**vars(s)) for s in result.steps])
