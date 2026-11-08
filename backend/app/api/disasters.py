"""Real disasters for the relief organization: FEMA declarations and severe National Weather Service warnings, a
preview of each one's zone, and opening (or closing) it in Hearthline."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import real_disasters
from app.auth import require_role
from app.db import get_db
from app.models import DisasterEvent, DisasterKind, Household, Role, User

router = APIRouter(prefix="/command/disasters", tags=["disasters"])
DB = Annotated[Session, Depends(get_db)]
OrgStaff = Annotated[User, Depends(require_role(Role.ORG_ADMIN, Role.SUPERVISOR))]


class EventOut(BaseModel):
    id: int
    name: str
    kind: str
    source: str  # demo | fema | nws
    external_id: str | None
    is_fictional: bool
    status: str  # active | closed
    declared_at: datetime
    households: int
    opened_by: str | None
    zone: dict


class DeclarationOut(BaseModel):
    number: int
    code: str
    state: str
    declared_at: datetime
    incident: str
    kind: str
    title: str
    areas: list[str]
    counties: int
    unmapped: list[str]
    opened_event_id: int | None


class WarningOut(BaseModel):
    id: str
    event: str
    kind: str
    severity: str
    headline: str
    area: str
    sent: datetime
    expires: datetime | None
    has_shape: bool
    counties: int
    first_72_hours: bool
    opened_event_id: int | None


class ZoneOut(BaseModel):
    zone: dict
    households: int  # households already on file inside it (and not in another open disaster)


class WarningIn(BaseModel):
    alert_id: str = Field(min_length=1, max_length=200)


def _fail(e: real_disasters.RealDisasterError) -> HTTPException:
    return HTTPException(503 if isinstance(e, real_disasters.Unavailable) else 409, str(e))


def _opened(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(DisasterEvent.external_id, DisasterEvent.id).where(
            DisasterEvent.status == "active", DisasterEvent.external_id.is_not(None)
        )
    )
    return {external_id: event_id for external_id, event_id in rows}


def _event(db: Session, e: DisasterEvent, households: int | None = None) -> EventOut:
    if households is None:
        households = db.scalar(select(func.count(Household.id)).where(Household.disaster_event_id == e.id)) or 0
    return EventOut(
        id=e.id,
        name=e.name,
        kind=e.kind,
        source=e.source,
        external_id=e.external_id,
        is_fictional=e.is_fictional,
        status=e.status,
        declared_at=e.declared_at,
        households=households,
        opened_by=e.opened_by,
        zone=e.zone,
    )


@router.get("", response_model=list[EventOut])
def events(_staff: OrgStaff, db: DB) -> list[EventOut]:
    counts = dict(
        db.execute(select(Household.disaster_event_id, func.count(Household.id)).group_by(Household.disaster_event_id))
        .tuples()
        .all()
    )
    found = db.scalars(select(DisasterEvent).order_by(DisasterEvent.status, DisasterEvent.declared_at.desc()))
    return [_event(db, e, counts.get(e.id, 0)) for e in found]


@router.get("/fema", response_model=list[DeclarationOut])
def fema(_staff: OrgStaff, db: DB) -> list[DeclarationOut]:
    """Disasters FEMA declared in the last four months (OpenFEMA), newest first."""
    try:
        found = real_disasters.declarations()
    except real_disasters.RealDisasterError as e:
        raise _fail(e) from None
    opened = _opened(db)
    return [
        DeclarationOut(
            number=d.number,
            code=d.code,
            state=d.state,
            declared_at=d.declared_at,
            incident=d.incident,
            kind=real_disasters.FEMA_KINDS.get(d.incident, DisasterKind.OTHER),
            title=d.title,
            areas=d.areas,
            counties=len(d.counties),
            unmapped=d.unmapped,
            opened_event_id=opened.get(d.code),
        )
        for d in found
    ]


@router.get("/fema/{number}/zone", response_model=ZoneOut)
def fema_zone(number: int, _staff: OrgStaff, db: DB) -> ZoneOut:
    try:
        _, zone = real_disasters.preview_declaration(db, number)
    except real_disasters.RealDisasterError as e:
        raise _fail(e) from None
    return ZoneOut(zone=zone.geometry, households=zone.households)


@router.post("/fema/{number}", response_model=EventOut, status_code=201)
def open_fema(number: int, staff: OrgStaff, db: DB) -> EventOut:
    try:
        event = real_disasters.open_declaration(db, number, staff)
    except real_disasters.RealDisasterError as e:
        raise _fail(e) from None
    return _event(db, event)


@router.get("/nws", response_model=list[WarningOut])
def nws(_staff: OrgStaff, db: DB) -> list[WarningOut]:
    """Active severe and extreme National Weather Service warnings."""
    try:
        found = real_disasters.warnings()
    except real_disasters.RealDisasterError as e:
        raise _fail(e) from None
    opened = _opened(db)
    return [
        WarningOut(
            id=w.id,
            event=w.event,
            kind=real_disasters.nws_kind(w.event),
            severity=w.severity,
            headline=w.headline,
            area=w.area,
            sent=w.sent,
            expires=w.expires,
            has_shape=w.geometry is not None,
            counties=len(w.counties),
            first_72_hours=w.first_72_hours,
            opened_event_id=opened.get(w.id),
        )
        for w in found
    ]


@router.get("/nws/zone", response_model=ZoneOut)
def nws_zone(_staff: OrgStaff, db: DB, alert_id: Annotated[str, Query(max_length=200)]) -> ZoneOut:
    try:
        _, zone = real_disasters.preview_warning(db, alert_id)
    except real_disasters.RealDisasterError as e:
        raise _fail(e) from None
    return ZoneOut(zone=zone.geometry, households=zone.households)


@router.post("/nws", response_model=EventOut, status_code=201)
def open_nws(body: WarningIn, staff: OrgStaff, db: DB) -> EventOut:
    try:
        event = real_disasters.open_warning(db, body.alert_id, staff)
    except real_disasters.RealDisasterError as e:
        raise _fail(e) from None
    return _event(db, event)


@router.post("/{event_id}/close", response_model=EventOut)
def close(event_id: int, staff: OrgStaff, db: DB) -> EventOut:
    event = db.get(DisasterEvent, event_id)
    if event is None:
        raise HTTPException(404, "Disaster not found")
    try:
        real_disasters.close(db, event, staff)
    except real_disasters.RealDisasterError as e:
        raise _fail(e) from None
    return _event(db, event)
