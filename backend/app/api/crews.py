"""Crew dispatch for Bryntum Scheduler Pro: crews are resources, visits to households are events.

CrudManager protocol: load returns resources, events and assignments; sync receives changes. Jobs come
from household needs, so they can be moved, reassigned and marked done here, but not created or deleted.
"""

import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Body, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, dispatch
from app.auth import require_role
from app.db import get_db
from app.models import Crew, CrewJob, DispatchProposal, Role, User

router = APIRouter(tags=["crews"])
DB = Annotated[Session, Depends(get_db)]
Dispatcher = Annotated[User, Depends(require_role(Role.ORG_ADMIN, Role.SUPERVISOR))]

UNASSIGNED = "unassigned"  # the resource row for jobs no crew has yet
KIND_COLOR = {
    "debris_removal": "red",
    "tarp_roof": "violet",
    "water": "blue",
    "food": "orange",
    "cleanup": "teal",
    "wellness": "green",
}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _parse(value: str) -> datetime:
    return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _event(j: CrewJob) -> dict:
    done = j.status == "done"
    h = j.household
    return {
        "id": j.id,
        "name": j.title,
        "startDate": _aware(j.starts_at).isoformat(),
        "endDate": _aware(j.ends_at).isoformat(),
        "manuallyScheduled": True,  # the dispatcher sets times; the engine shouldn't move them
        "preamble": f"{j.travel_minutes} minutes",  # travel time, drawn before the job
        "eventColor": "gray" if done else KIND_COLOR.get(j.kind, "blue"),
        "draggable": not done,
        "resizable": not done,
        "cls": "job-done" if done else "",
        "kind": j.kind,
        "status": j.status,
        "household": h.name,
        "address": h.address_line,
        "damage": h.damage_level,
        "people": h.household_size,
    }


@router.get("/bryntum/crews/load")
def crews_load(
    staff: Dispatcher,
    db: DB,
    requestId: int | None = None,  # noqa: N803
    data: str | None = None,
) -> dict:
    if requestId is None and data:
        try:
            requestId = json.loads(data).get("requestId")  # noqa: N806
        except (ValueError, AttributeError):
            pass
    crews = list(db.scalars(select(Crew).order_by(Crew.id)))
    jobs = list(db.scalars(select(CrewJob).where(CrewJob.status != "cancelled").order_by(CrewJob.starts_at)))
    resources = [{"id": UNASSIGNED, "name": "", "kind": "", "lead": "", "size": 0}] + [
        {"id": c.id, "name": c.name, "kind": c.kind, "lead": c.lead_name, "size": c.size} for c in crews
    ]
    # The dispatch agent's open proposals: ghost bars on the crew it proposes (read-only; accepted in the panel)
    plan = dispatch.latest(db)
    ghosts = [p for p in plan.proposals if p.status == "proposed"] if plan else []
    return {
        "success": True,
        "requestId": requestId,
        "resources": {"rows": resources},
        "events": {"rows": [_event(j) for j in jobs] + [_ghost(p) for p in ghosts]},
        # One assignment per job, with the job's id, so moving a job between rows is an update.
        "assignments": {
            "rows": [{"id": j.id, "eventId": j.id, "resourceId": j.crew_id or UNASSIGNED} for j in jobs]
            + [{"id": f"p{p.id}", "eventId": f"p{p.id}", "resourceId": p.crew_id} for p in ghosts]
        },
    }


def _ghost(p: DispatchProposal) -> dict:
    """A proposal drawn where the agent would put the job: dashed, not draggable, with the agent's reason."""
    return {
        **_event(p.job),
        "id": f"p{p.id}",
        "startDate": _aware(p.starts_at).isoformat(),
        "endDate": _aware(p.ends_at).isoformat(),
        "preamble": f"{p.travel_minutes} minutes",
        "draggable": False,
        "resizable": False,
        "cls": "job-proposal",
        "proposal": p.id,
        "reason": p.reason,
    }


def _fail(request_id, message: str) -> dict:
    return {"success": False, "requestId": request_id, "message": message}


@router.post("/bryntum/crews/sync")
def crews_sync(staff: Dispatcher, db: DB, payload: Annotated[dict, Body()]) -> dict:
    request_id = payload.get("requestId")
    events = payload.get("events") or {}
    assignments = payload.get("assignments") or {}
    if events.get("added") or events.get("removed") or assignments.get("added") or assignments.get("removed"):
        return _fail(
            request_id, "Jobs come from household needs: move or reassign them, but don't add or delete them here."
        )
    crews = {c.id for c in db.scalars(select(Crew))}
    changed_events, changed_assignments = [], []

    for row in events.get("updated", []):
        if not isinstance(row.get("id"), int):  # a proposal's ghost: decided in the dispatch panel, not here
            continue
        job = db.get(CrewJob, row.get("id"))
        if job is None:
            continue
        moving = {"startDate", "endDate"} & row.keys()
        if moving and job.status == "done":
            db.rollback()
            return _fail(request_id, "That job is already done.")
        if "startDate" in row:
            job.starts_at = _parse(row["startDate"])
        if "endDate" in row:
            job.ends_at = _parse(row["endDate"])
        if _aware(job.ends_at) <= _aware(job.starts_at):
            db.rollback()
            return _fail(request_id, "A job has to end after it starts.")
        if row.get("status") in {"scheduled", "done"}:
            job.status = row["status"]
        audit.record(
            db,
            actor_user_id=staff.id,
            action="crew_job.updated",
            subject_type="crew_job",
            subject_id=job.id,
            data={"start": job.starts_at.isoformat(), "end": job.ends_at.isoformat(), "status": job.status},
        )
        changed_events.append(
            {"id": job.id, **({"eventColor": "gray", "cls": "job-done"} if job.status == "done" else {})}
        )

    for row in assignments.get("updated", []):
        if not isinstance(row.get("eventId", row.get("id")), int):
            continue
        job = db.get(CrewJob, row.get("eventId", row.get("id")))
        if job is None or "resourceId" not in row:
            continue
        target = row["resourceId"]
        if target != UNASSIGNED and target not in crews:
            db.rollback()
            return _fail(request_id, "Unknown crew.")
        job.crew_id = None if target == UNASSIGNED else target
        audit.record(
            db,
            actor_user_id=staff.id,
            action="crew_job.assigned",
            subject_type="crew_job",
            subject_id=job.id,
            data={"crew_id": job.crew_id},
        )
        changed_assignments.append({"id": row["id"]})

    db.commit()
    return {
        "success": True,
        "requestId": request_id,
        "events": {"rows": changed_events},
        "assignments": {"rows": changed_assignments},
    }
