"""Cases: households submit, reviewers decide. Staff never pick their own cases."""

import random
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import review, trust
from app.api.households import MyHousehold
from app.auth import CurrentUser, require_role
from app.db import get_db
from app.media import media_url
from app.models import Case, Item, Media, Registry, Role, User
from app.schemas import ORM, Money

router = APIRouter(tags=["review"])
DB = Annotated[Session, Depends(get_db)]
Staff = Annotated[User, Depends(require_role(Role.REVIEWER, Role.SUPERVISOR, Role.ORG_ADMIN))]
RNG = random.Random()


class CaseIn(BaseModel):
    kind: Literal["cash_aid", "contents_claim"]
    amount: Money = Field(default=Decimal(0), ge=0, le=Decimal("25000"))
    note: str = Field(default="", max_length=1000)


class ReplyIn(BaseModel):
    note: str = Field(min_length=3, max_length=1000)


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "request_info"]
    reason: str = Field(default="", max_length=1000)


class ReviewOut(ORM):
    reviewer_name: str
    role: str
    decision: str
    reason: str
    created_at: datetime


class HouseholdCaseOut(ORM):
    """What the household sees: status and any question for them, not the fraud signals."""

    id: int
    kind: str
    title: str
    amount_requested: Money
    status: str
    video_call_required: bool
    decision_note: str | None
    created_at: datetime
    decided_at: datetime | None


class QueueRowOut(ORM):
    id: int
    kind: str
    title: str
    household_id: int
    household_name: str
    city: str
    amount_requested: Money
    status: str
    risk_score: int
    risk_tier: str
    flag_count: int
    required_reviews: int
    reviews_done: int
    video_call_required: bool
    my_role: str | None
    awaiting_me: bool
    created_at: datetime


class EvidencePhoto(BaseModel):
    media_id: int
    url: str
    captured_at: datetime | None


class CaseDetailOut(QueueRowOut):
    note: str
    flags: list[dict]
    sentinel_summary: str
    sentinel_questions: list[str]
    sentinel_recommendation: str | None
    random_audit: bool
    decision_note: str | None
    paypal_ref: str | None
    address: str
    lat: float | None
    lng: float | None
    in_disaster_zone: bool
    verification_level: int
    payout_email: str | None
    vouch_note: str | None
    inventory_items: int
    inventory_value: Money
    registry_slug: str | None
    photos: list[EvidencePhoto]
    reviews: list[ReviewOut]
    reviewers: list[str]


def _mask(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    name, domain = email.split("@", 1)
    return f"{name[:2]}***@{domain}"


def queue_row(case: Case, me: User) -> QueueRowOut:
    mine = next((a for a in case.assignments if a.reviewer_user_id == me.id), None)
    reviewed = any(r.reviewer_user_id == me.id for r in case.reviews)
    awaiting = mine is not None and (
        (case.status == "in_review" and not reviewed) or (case.status == "escalated" and mine.role == Role.SUPERVISOR)
    )
    return QueueRowOut(
        id=case.id,
        kind=case.kind,
        title=case.title,
        household_id=case.household_id,
        household_name=case.household.name,
        city=case.household.city,
        amount_requested=case.amount_requested,
        status=case.status,
        risk_score=case.risk_score,
        risk_tier=case.risk_tier,
        flag_count=len(case.flags),
        required_reviews=case.required_reviews,
        reviews_done=len([r for r in case.reviews if r.decision != "request_info"]),
        video_call_required=case.video_call_required,
        my_role=mine.role if mine else None,
        awaiting_me=awaiting,
        created_at=case.created_at,
    )


def get_case(db: Session, case_id: int) -> Case:
    case = db.get(Case, case_id)
    if case is None:
        raise HTTPException(404, "Case not found")
    return case


def can_see(case: Case, me: User) -> bool:
    return me.role in {Role.SUPERVISOR, Role.ORG_ADMIN} or review.is_assigned(case, me)


# --- Household -------------------------------------------------------------------------------


@router.post("/households/me/cases", response_model=HouseholdCaseOut, status_code=201)
def submit_case(body: CaseIn, home: MyHousehold, user: CurrentUser, db: DB) -> Case:
    title = {"cash_aid": "Cash aid request", "contents_claim": "Contents claim review"}[body.kind]
    try:
        return review.open_case(
            db, home, kind=body.kind, title=title, amount=body.amount, note=body.note, actor_user_id=user.id, rng=RNG
        )
    except review.ReviewError as e:
        raise HTTPException(409, str(e)) from None


@router.get("/households/me/cases", response_model=list[HouseholdCaseOut])
def my_cases(home: MyHousehold, db: DB) -> list[Case]:
    return list(db.scalars(select(Case).where(Case.household_id == home.id).order_by(Case.id.desc())))


@router.post("/households/me/cases/{case_id}/reply", response_model=HouseholdCaseOut)
def reply(case_id: int, body: ReplyIn, home: MyHousehold, user: CurrentUser, db: DB) -> Case:
    case = get_case(db, case_id)
    if case.household_id != home.id:
        raise HTTPException(404, "Case not found")
    try:
        return review.respond(db, case, body.note, user.id)
    except review.ReviewError as e:
        raise HTTPException(409, str(e)) from None


# --- Reviewers ---------------------------------------------------------------------------------


@router.get("/review/queue", response_model=list[QueueRowOut])
def queue(me: Staff, db: DB) -> list[QueueRowOut]:
    cases = db.scalars(select(Case).order_by(Case.created_at.desc()))
    return [queue_row(c, me) for c in cases if can_see(c, me)]


@router.get("/review/cases/{case_id}", response_model=CaseDetailOut)
def case_detail(case_id: int, me: Staff, db: DB) -> CaseDetailOut:
    case = get_case(db, case_id)
    if not can_see(case, me):
        raise HTTPException(404, "Case not found")
    home = case.household
    items = list(db.scalars(select(Item).where(Item.household_id == home.id)))
    photos = db.scalars(select(Media).where(Media.household_id == home.id).order_by(Media.id).limit(8))
    reg = db.scalar(select(Registry).where(Registry.household_id == home.id))
    return CaseDetailOut(
        **queue_row(case, me).model_dump(),
        note=case.note,
        flags=case.flags,
        sentinel_summary=case.sentinel_summary,
        sentinel_questions=case.sentinel_questions,
        sentinel_recommendation=case.sentinel_recommendation,
        random_audit=case.random_audit,
        decision_note=case.decision_note,
        paypal_ref=case.paypal_ref,
        address=f"{home.address_line}, {home.city}, {home.state} {home.postal_code}",
        lat=home.lat,
        lng=home.lng,
        in_disaster_zone=trust.in_disaster_zone(home),
        verification_level=trust.verification_level(db, home),
        payout_email=_mask(home.payout_email),
        vouch_note=home.vouch_note,
        inventory_items=len(items),
        inventory_value=sum((i.total_value or Decimal(0) for i in items), Decimal(0)),
        registry_slug=reg.slug if reg else None,
        photos=[EvidencePhoto(media_id=m.id, url=media_url(m.id), captured_at=m.captured_at) for m in photos],
        reviews=[
            ReviewOut(
                reviewer_name=r.reviewer.name,
                role=r.role,
                decision=r.decision,
                reason=r.reason,
                created_at=r.created_at,
            )
            for r in case.reviews
        ],
        reviewers=[f"{a.reviewer.name} ({a.role})" for a in case.assignments],
    )


@router.post("/review/cases/{case_id}/decision", response_model=QueueRowOut)
def decide(case_id: int, body: DecisionIn, me: Staff, db: DB) -> QueueRowOut:
    case = get_case(db, case_id)
    try:
        review.decide(db, case, me, body.decision, body.reason, rng=RNG)
    except review.ReviewError as e:
        db.rollback()
        raise HTTPException(409, str(e)) from None
    return queue_row(case, me)
