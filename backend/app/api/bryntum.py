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

from app import audit, rebuild_schedule, review
from app.api.households import MyHousehold
from app.auth import CurrentUser, require_role
from app.db import get_db
from app.models import Appointment, Case, RebuildProject, Role, User

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


# --- Bryntum CrudManager: Gantt (one rebuild project) ---------------------------------------------

MILESTONE_COLOR = {
    "pending": "gray",
    "submitted": "orange",
    "under_review": "orange",
    "paid": "green",
    "disputed": "red",
    "refunded": "red",
}
MILESTONE_PROGRESS = {"submitted": 50, "under_review": 75, "paid": 100}
# The family's move-in day: a milestone after the last steps. Bryntum links a dependency only to a numeric task id,
# so it gets a number no milestone will reach.
MOVE_IN = 2_000_000_000


def _gantt_project(db: Session, project_id: int, user: User) -> RebuildProject:
    from app.api.rebuild import project_for  # the same visibility rules as the project API

    return project_for(db, project_id, user)


@router.get("/bryntum/gantt/{project_id}/load")
def gantt_load(
    project_id: int,
    user: CurrentUser,
    db: DB,
    requestId: int | None = None,
    data: str | None = None,  # noqa: N803
) -> dict:
    p = _gantt_project(db, project_id, user)
    milestones = list(p.milestones)
    children = []
    for m in milestones:
        start, end = _aware(m.start_date).isoformat(), _aware(m.end_date).isoformat()
        pending = m.status == "pending"
        row = {
            "id": m.id,
            "name": f"{m.seq}. {m.title} · ${m.amount:,.0f}",
            "startDate": start,
            "endDate": end,
            # Submitted and paid work stays put; Bryntum's engine schedules the rest: no earlier than planned, and
            # not before the steps it waits for end (the same rules as app.rebuild_schedule)
            "manuallyScheduled": not pending,
            "percentDone": MILESTONE_PROGRESS.get(m.status, 0),
            "eventColor": MILESTONE_COLOR.get(m.status, "blue"),
            "status": m.status,
            "amount": str(m.amount),
        }
        if pending:
            row |= {"constraintType": "startnoearlierthan", "constraintDate": start}
        if m.baseline_start and m.baseline_end:  # the plan the homeowner accepted
            row["baselines"] = [
                {"startDate": _aware(m.baseline_start).isoformat(), "endDate": _aware(m.baseline_end).isoformat()}
            ]
        children.append(row)
    move_in = rebuild_schedule.move_in(milestones)
    if move_in is not None:
        planned = rebuild_schedule.move_in(milestones, baseline=True)
        children.append(
            {
                "id": MOVE_IN,
                "name": "Move-in day",
                "startDate": move_in.isoformat(),
                "duration": 0,
                "durationUnit": "day",
                "status": "move_in",
                "percentDone": 0,
                **(
                    {"baselines": [{"startDate": planned.isoformat(), "endDate": planned.isoformat()}]}
                    if planned
                    else {}
                ),
            }
        )
    root = {"id": f"project-{p.id}", "name": p.title, "expanded": True, "children": children}  # dates roll up
    by_seq = {m.seq: m for m in milestones}
    deps = [  # finish-to-start
        {"id": f"{by_seq[s].id}-{m.id}", "fromTask": by_seq[s].id, "toTask": m.id, "type": 2}
        for m in milestones
        for s in rebuild_schedule.predecessors(m)
        if s in by_seq
    ] + [
        {"id": f"{m.id}-{MOVE_IN}", "fromTask": m.id, "toTask": MOVE_IN, "type": 2}
        for m in rebuild_schedule.last_steps(milestones)
    ]
    return {
        "success": True,
        "requestId": _request_id(requestId, data),
        # Every day counts, as on a building site's contract: a 14-day step takes 14 calendar days
        "project": {"calendar": "every-day", "hoursPerDay": 24, "daysPerWeek": 7, "daysPerMonth": 30},
        "calendars": {"rows": [{"id": "every-day", "name": "Every day", "unspecifiedTimeIsWorking": True}]},
        "tasks": {"rows": [root]},
        "dependencies": {"rows": deps},
    }


@router.post("/bryntum/gantt/{project_id}/sync")
def gantt_sync(project_id: int, user: CurrentUser, db: DB, payload: Annotated[dict, Body()]) -> dict:
    """Only the project's contractor may move dates, and only for work that hasn't been submitted yet."""
    p = _gantt_project(db, project_id, user)
    request_id = payload.get("requestId")
    if p.contractor.user_id != user.id:
        return {"success": False, "requestId": request_id, "message": "Only the contractor can change the schedule."}
    tasks = payload.get("tasks") or {}
    if tasks.get("added") or tasks.get("removed"):
        return {
            "success": False,
            "requestId": request_id,
            "message": "Change milestones through the plan, not the chart.",
        }
    by_id = {m.id: m for m in p.milestones}
    changed = []
    for row in tasks.get("updated", []):
        m = by_id.get(row.get("id"))
        if m is None or m.status != "pending" or not ({"startDate", "endDate"} & row.keys()):
            continue
        length = _aware(m.end_date) - _aware(m.start_date)
        if "startDate" in row:
            m.start_date = _aware(datetime.fromisoformat(row["startDate"]))
        m.end_date = _aware(datetime.fromisoformat(row["endDate"])) if "endDate" in row else m.start_date + length
        if m.end_date < m.start_date:
            db.rollback()
            return {"success": False, "requestId": request_id, "message": "A milestone can't end before it starts."}
        audit.record(
            db,
            actor_user_id=user.id,
            action="milestone.rescheduled",
            subject_type="milestone",
            subject_id=m.id,
            data={"start": m.start_date.isoformat(), "end": m.end_date.isoformat()},
        )
        changed.append({"id": m.id})
    problems = rebuild_schedule.violations(list(p.milestones))
    if problems:
        db.rollback()
        return {"success": False, "requestId": request_id, "message": problems[0]}
    db.commit()
    return {"success": True, "requestId": request_id, "tasks": {"rows": changed}}
