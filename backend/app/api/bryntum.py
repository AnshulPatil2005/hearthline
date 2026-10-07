"""Video-verification calls, plus Bryntum's CrudManager load/sync protocol for the Calendar
(calls per reviewer) and the TaskBoard (cases by status).

Protocol: load returns {"success", "requestId", <store>: {"rows": [...]}}; sync receives
{<store>: {"added", "updated", "removed"}} and answers with the rows it changed.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, review
from app.api.households import MyHousehold
from app.auth import require_role
from app.db import get_db
from app.models import Appointment, Case, Role, User

router = APIRouter(tags=["calendar"])
DB = Annotated[Session, Depends(get_db)]
Staff = Annotated[User, Depends(require_role(Role.REVIEWER, Role.SUPERVISOR, Role.ORG_ADMIN))]
CALL_LENGTH = timedelta(minutes=20)
RISK_COLOR = {"low": "green", "medium": "orange", "high": "red"}


class BookIn(BaseModel):
    starts_at: datetime


class AppointmentOut(BaseModel):
    id: int
    case_id: int
    reviewer_name: str
    household_name: str
    starts_at: datetime
    ends_at: datetime
    status: str


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _out(a: Appointment) -> AppointmentOut:
    return AppointmentOut(
        id=a.id,
        case_id=a.case_id,
        reviewer_name=a.reviewer.name,
        household_name=a.case.household.name,
        starts_at=_aware(a.starts_at),
        ends_at=_aware(a.ends_at),
        status=a.status,
    )


def _own_appointment(db: Session, me: User, appointment_id: int) -> Appointment:
    appt = db.get(Appointment, appointment_id)
    if appt is None or (appt.reviewer_user_id != me.id and me.role == Role.REVIEWER):
        raise HTTPException(404, "Appointment not found")
    return appt


@router.post("/review/cases/{case_id}/appointments", response_model=AppointmentOut, status_code=201)
def book_call(case_id: int, body: BookIn, me: Staff, db: DB) -> AppointmentOut:
    case = db.get(Case, case_id)
    if case is None or not review.is_assigned(case, me):
        raise HTTPException(404, "Case not found")
    starts = _aware(body.starts_at)
    appt = Appointment(case_id=case.id, reviewer_user_id=me.id, starts_at=starts, ends_at=starts + CALL_LENGTH)
    db.add(appt)
    db.flush()
    audit.record(
        db,
        actor_user_id=me.id,
        action="call.booked",
        subject_type="case",
        subject_id=case.id,
        data={"starts_at": starts.isoformat()},
    )
    db.commit()
    return _out(appt)


@router.post("/review/appointments/{appointment_id}/complete", response_model=AppointmentOut)
def complete_call(appointment_id: int, me: Staff, db: DB) -> AppointmentOut:
    appt = _own_appointment(db, me, appointment_id)
    appt.status = "completed"
    audit.record(db, actor_user_id=me.id, action="call.completed", subject_type="case", subject_id=appt.case_id)
    db.commit()
    return _out(appt)


@router.get("/review/cases/{case_id}/appointments", response_model=list[AppointmentOut])
def case_calls(case_id: int, me: Staff, db: DB) -> list[AppointmentOut]:
    calls = db.scalars(select(Appointment).where(Appointment.case_id == case_id).order_by(Appointment.starts_at))
    return [_out(a) for a in calls]


@router.get("/households/me/appointments", response_model=list[AppointmentOut])
def my_calls(home: MyHousehold, db: DB) -> list[AppointmentOut]:
    calls = db.scalars(
        select(Appointment)
        .join(Case)
        .where(Case.household_id == home.id, Appointment.status == "scheduled")
        .order_by(Appointment.starts_at)
    )
    return [_out(a) for a in calls]


# --- Bryntum CrudManager: Calendar -------------------------------------------------------------


def _request_id(request_id: int | None, data: str | None) -> int | None:
    """CrudManager sends load params as a JSON `data` query parameter; echo its requestId back."""
    if request_id is None and data:
        try:
            request_id = json.loads(data).get("requestId")
        except (ValueError, AttributeError):
            pass
    return request_id


def _event_row(a: Appointment) -> dict:
    return {
        "id": a.id,
        "name": f"Video call · {a.case.household.name}",
        "startDate": _aware(a.starts_at).isoformat(),
        "endDate": _aware(a.ends_at).isoformat(),
        "resourceId": a.reviewer_user_id,
        "eventColor": "gray" if a.status == "completed" else RISK_COLOR.get(a.case.risk_tier, "blue"),
        "caseId": a.case_id,
        "status": a.status,
    }


@router.get("/bryntum/calendar/load")
def calendar_load(me: Staff, db: DB, requestId: int | None = None, data: str | None = None) -> dict:  # noqa: N803
    staff = db.scalars(select(User).where(User.role.in_([Role.REVIEWER, Role.SUPERVISOR])).order_by(User.id))
    visible = select(Appointment).where(Appointment.status != "cancelled")
    if me.role == Role.REVIEWER:
        visible = visible.where(Appointment.reviewer_user_id == me.id)
    return {
        "success": True,
        "requestId": _request_id(requestId, data),
        "resources": {
            "rows": [{"id": u.id, "name": u.name, "eventColor": "orange" if u.id == me.id else "blue"} for u in staff]
        },
        "events": {"rows": [_event_row(a) for a in db.scalars(visible)]},
    }


@router.post("/bryntum/calendar/sync")
def calendar_sync(me: Staff, db: DB, payload: Annotated[dict, Body()]) -> dict:
    """Reviewers drag calls to reschedule them or delete them to cancel. New calls are booked from a
    case (so every call belongs to a case), not by drawing on the calendar."""
    events = payload.get("events") or {}
    if events.get("added"):
        return {
            "success": False,
            "requestId": payload.get("requestId"),
            "message": "Book calls from a case so each call is linked to the household.",
        }
    changed = []
    for row in events.get("updated", []):
        appt = _own_appointment(db, me, int(row["id"]))
        if "startDate" in row:
            appt.starts_at = _aware(datetime.fromisoformat(row["startDate"]))
        if "endDate" in row:
            appt.ends_at = _aware(datetime.fromisoformat(row["endDate"]))
        audit.record(
            db,
            actor_user_id=me.id,
            action="call.rescheduled",
            subject_type="case",
            subject_id=appt.case_id,
            data={"starts_at": appt.starts_at.isoformat()},
        )
        changed.append({"id": appt.id})
    for row in events.get("removed", []):
        appt = _own_appointment(db, me, int(row["id"]))
        appt.status = "cancelled"
        audit.record(db, actor_user_id=me.id, action="call.cancelled", subject_type="case", subject_id=appt.case_id)
    db.commit()
    return {"success": True, "requestId": payload.get("requestId"), "events": {"rows": changed}}


# --- Bryntum CrudManager: TaskBoard (read-only case pipeline) -----------------------------------


@router.get("/bryntum/board/load")
def board_load(me: Staff, db: DB, requestId: int | None = None, data: str | None = None) -> dict:  # noqa: N803
    cases = [
        c for c in db.scalars(select(Case).order_by(Case.id)) if me.role != Role.REVIEWER or review.is_assigned(c, me)
    ]
    return {
        "success": True,
        "requestId": _request_id(requestId, data),
        "tasks": {
            "rows": [
                {
                    "id": c.id,
                    "name": f"{c.household.name}",
                    "description": f"{c.title} · risk {c.risk_score}",
                    "status": c.status,
                    "eventColor": RISK_COLOR.get(c.risk_tier, "blue"),
                    "kind": c.kind,
                }
                for c in cases
            ]
        },
    }
