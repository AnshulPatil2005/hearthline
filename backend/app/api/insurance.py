"""The household's insurance policy: upload it, see what the Policy agent read, and ask questions."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, audit, claims
from app.agents import policy_agent
from app.api.households import MyHousehold
from app.auth import CurrentUser
from app.db import get_db
from app.models import InsurancePolicy, Item

router = APIRouter(tags=["insurance"])
DB = Annotated[Session, Depends(get_db)]
MAX_PDF_BYTES = 15 * 1024 * 1024


class PolicyOut(BaseModel):
    filename: str
    uploaded_at: datetime
    summary: policy_agent.PolicySummary
    check: claims.ClaimCheck


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)


def _latest(db: Session, household_id: int) -> InsurancePolicy | None:
    return db.scalar(
        select(InsurancePolicy)
        .where(InsurancePolicy.household_id == household_id, InsurancePolicy.summary.is_not(None))
        .order_by(InsurancePolicy.id.desc())
    )


def _out(db: Session, policy: InsurancePolicy, home) -> PolicyOut:
    summary = policy_agent.PolicySummary.model_validate(policy.summary)
    items = list(db.scalars(select(Item).where(Item.household_id == home.id)))
    return PolicyOut(
        filename=policy.filename,
        uploaded_at=policy.created_at,
        summary=summary,
        check=claims.check(summary, home, items),
    )


@router.post("/households/me/policy", response_model=PolicyOut, status_code=201)
def upload_policy(file: UploadFile, home: MyHousehold, user: CurrentUser, db: DB) -> PolicyOut:
    data = file.file.read()
    if len(data) > MAX_PDF_BYTES:
        raise HTTPException(413, "That PDF is over 15 MB")
    try:
        text = policy_agent.pdf_text(data)
    except policy_agent.NotAPolicy as e:
        raise HTTPException(422, str(e)) from None
    policy = InsurancePolicy(household_id=home.id, filename=(file.filename or "policy.pdf")[:200], pdf=data, text=text)
    db.add(policy)
    try:
        policy.summary = policy_agent.read(text).model_dump()
    except ai.AIError:
        policy.error = "The Policy agent couldn't read it right now"
        db.commit()
        raise HTTPException(
            503, "The Policy agent couldn't read your policy right now. Try again in a minute."
        ) from None
    db.flush()
    audit.record(
        db,
        actor_user_id=user.id,
        action="policy.read",
        subject_type="insurance_policy",
        subject_id=policy.id,
        data={"insurer": policy.summary.get("insurer"), "filename": policy.filename},
    )
    db.commit()
    return _out(db, policy, home)


@router.get("/households/me/policy", response_model=PolicyOut)
def get_policy(home: MyHousehold, db: DB) -> PolicyOut:
    policy = _latest(db, home.id)
    if policy is None:
        raise HTTPException(404, "No policy uploaded yet")
    return _out(db, policy, home)


@router.post("/households/me/policy/ask", response_model=policy_agent.PolicyAnswer)
def ask_policy(body: AskIn, home: MyHousehold, db: DB) -> policy_agent.PolicyAnswer:
    policy = _latest(db, home.id)
    if policy is None:
        raise HTTPException(404, "Upload your policy first")
    try:
        return policy_agent.ask(policy.text, body.question)
    except ai.AIError:
        raise HTTPException(503, "The Policy agent couldn't answer right now. Try again in a minute.") from None
