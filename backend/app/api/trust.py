from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import audit, trust
from app.api.households import MyHousehold
from app.auth import require_role
from app.db import get_db
from app.models import Household, Role, User

router = APIRouter(tags=["trust"])
DB = Annotated[Session, Depends(get_db)]
Staff = Annotated[User, Depends(require_role(Role.REVIEWER, Role.SUPERVISOR, Role.ORG_ADMIN))]

NEXT_STEP = {
    0: "address_outside_zone",
    1: "confirm_residence",  # upload proof of residence, or ask a caseworker to vouch
    2: "scan_before_disaster",
    3: None,
}


class VerificationOut(BaseModel):
    level: int
    level_name: str
    in_disaster_zone: bool
    residence_verified: bool
    vouched: bool
    next_step: str | None


class FlagOut(BaseModel):
    code: str
    severity: str
    message: str
    evidence: dict


class TrustOut(BaseModel):
    household_id: int
    level: int
    risk_score: int
    risk_tier: str
    flags: list[FlagOut]


class VouchIn(BaseModel):
    note: str = Field(min_length=10, max_length=500)  # how the caseworker knows this family


@router.get("/households/me/verification", response_model=VerificationOut)
def my_verification(home: MyHousehold, db: DB) -> VerificationOut:
    level = trust.refresh_level(db, home)
    db.commit()
    return VerificationOut(
        level=level,
        level_name=trust.LEVEL_NAMES[level],
        in_disaster_zone=trust.in_disaster_zone(home),
        residence_verified=home.residence_verified,
        vouched=home.vouched_by_user_id is not None,
        next_step=NEXT_STEP[level],
    )


@router.get("/trust/households/{household_id}", response_model=TrustOut)
def household_trust(household_id: int, staff: Staff, db: DB) -> TrustOut:
    home = db.get(Household, household_id)
    if home is None:
        raise HTTPException(404, "Household not found")
    flags = trust.sentinel_flags(db, home)
    score, tier = trust.risk(flags)
    return TrustOut(
        household_id=home.id,
        level=trust.verification_level(db, home),
        risk_score=score,
        risk_tier=tier,
        flags=[FlagOut(**f) for f in trust.flags_json(flags)],
    )


@router.post("/trust/households/{household_id}/vouch", response_model=VerificationOut)
def vouch(household_id: int, body: VouchIn, staff: Staff, db: DB) -> VerificationOut:
    """A caseworker confirms they know this family lives at this address (for families who lost
    their documents). Recorded in the audit log with the caseworker's name."""
    home = db.get(Household, household_id)
    if home is None:
        raise HTTPException(404, "Household not found")
    if staff.household_id == home.id:
        raise HTTPException(403, "You can't vouch for your own household")
    home.vouched_by_user_id = staff.id
    home.vouch_note = body.note
    level = trust.refresh_level(db, home)
    audit.record(
        db,
        actor_user_id=staff.id,
        action="household.vouched",
        subject_type="household",
        subject_id=home.id,
        data={"note": body.note, "new_level": level},
    )
    db.commit()
    return VerificationOut(
        level=level,
        level_name=trust.LEVEL_NAMES[level],
        in_disaster_zone=trust.in_disaster_zone(home),
        residence_verified=home.residence_verified,
        vouched=True,
        next_step=NEXT_STEP[level],
    )
