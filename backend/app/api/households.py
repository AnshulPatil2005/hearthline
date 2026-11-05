from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, geo, trust
from app.auth import CurrentUser
from app.db import get_db
from app.models import DisasterEvent, Household
from app.schemas import ORM, Money

router = APIRouter(tags=["households"])
DB = Annotated[Session, Depends(get_db)]


class DisasterOut(ORM):
    id: int
    slug: str
    name: str
    kind: str
    status: str
    is_fictional: bool


class DisasterWithZoneOut(DisasterOut):
    zone: dict


class HouseholdOut(ORM):
    id: int
    name: str
    address_line: str
    city: str
    state: str
    postal_code: str
    lat: float | None
    lng: float | None
    insured_contents_value: Money | None
    verification_level: int
    disaster_event: DisasterOut | None
    in_disaster_zone: bool = False


class HouseholdUpdate(BaseModel):
    address_line: str | None = None
    city: str | None = None
    state: str | None = None
    postal_code: str | None = None
    insured_contents_value: Money | None = None


def my_household(user: CurrentUser, db: DB) -> Household:
    if user.household_id is None:
        raise HTTPException(404, "You are not part of a household")
    return db.get(Household, user.household_id)


MyHousehold = Annotated[Household, Depends(my_household)]


def household_out(home: Household) -> HouseholdOut:
    inside = bool(
        home.disaster_event and home.lat is not None and geo.in_zone(home.disaster_event.zone, home.lat, home.lng)
    )
    return HouseholdOut.model_validate(home, from_attributes=True).model_copy(update={"in_disaster_zone": inside})


@router.get("/disasters", response_model=list[DisasterWithZoneOut])
def list_disasters(db: DB) -> list[DisasterEvent]:
    return list(db.scalars(select(DisasterEvent).order_by(DisasterEvent.declared_at.desc())))


@router.get("/households/me", response_model=HouseholdOut)
def get_my_household(home: MyHousehold) -> HouseholdOut:
    return household_out(home)


@router.patch("/households/me", response_model=HouseholdOut)
def update_my_household(body: HouseholdUpdate, home: MyHousehold, db: DB) -> HouseholdOut:
    changes = body.model_dump(exclude_unset=True)
    address_changed = any(
        k in changes and changes[k] != getattr(home, k) for k in ("address_line", "city", "state", "postal_code")
    )
    for key, value in changes.items():
        setattr(home, key, value)
    if address_changed:
        point = geo.geocode(f"{home.address_line}, {home.city}, {home.state} {home.postal_code}")
        if point is None:
            raise HTTPException(422, "We couldn't find that address. Check it and try again.")
        home.lat, home.lng = point
        home.disaster_event = geo.event_for_point(db, *point)
        # Proof of residence was for the old address: a new one has to be proven again, or nobody could verify
        # a home inside the zone and then move the household's address to unlock aid somewhere else
        if home.residence_verified or home.vouched_by_user_id:
            audit.record(
                db,
                action="household.residence_reset",
                subject_type="household",
                subject_id=home.id,
                data={"reason": "address changed", "was_vouched_by": home.vouched_by_user_id},
            )
        home.residence_verified = False
        home.vouched_by_user_id = None
        home.vouch_note = None
        trust.refresh_level(db, home)
    db.commit()
    return household_out(home)
