"""Rebuild: households hire verified contractors; contractors plan milestones and submit work."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import rebuild, rebuild_schedule
from app.api.households import MyHousehold
from app.auth import CurrentUser, require_role
from app.db import get_db
from app.media import InvalidImage, media_url, prepare_image
from app.models import Contractor, Media, Milestone, RebuildProject, Role, ScheduleChange, User
from app.schemas import ORM, Money

router = APIRouter(tags=["rebuild"])
DB = Annotated[Session, Depends(get_db)]
ContractorUser = Annotated[User, Depends(require_role(Role.CONTRACTOR))]


class ContractorOut(ORM):
    id: int
    business_name: str
    license_number: str
    license_state: str
    license_verified: bool


class MilestoneIn(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    done_looks_like: str = Field(default="", max_length=1000)
    amount: Money = Field(gt=0)
    is_deposit: bool = False
    start_date: datetime
    end_date: datetime
    after: list[int] | None = Field(default=None, max_length=20)  # step numbers this one waits for


class PlanIn(BaseModel):
    milestones: list[MilestoneIn] = Field(min_length=1, max_length=20)


class ProjectIn(BaseModel):
    contractor_id: int
    title: str = Field(min_length=3, max_length=200)


class DisputeIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)


class MilestoneOut(ORM):
    id: int
    seq: int
    title: str
    done_looks_like: str
    amount: Money
    is_deposit: bool
    start_date: datetime
    end_date: datetime
    status: str
    site_check: dict | None
    case_id: int | None
    paypal_ref: str | None
    submitted_at: datetime | None
    paid_at: datetime | None
    photo_urls: list[str] = []
    needs_human_review: bool = False  # what happens when the homeowner approves (rules live in app.rebuild)
    after: list[int] | None = None
    baseline_start: datetime | None = None
    baseline_end: datetime | None = None
    slack_days: int | None = None  # how late it can run before move-in moves (steps not yet submitted)


class ScheduleChangeOut(ORM):
    id: int
    milestone_id: int
    milestone_title: str
    days: int
    reason: str
    moved: list[dict]
    move_in_before: datetime
    move_in_after: datetime
    created_at: datetime


class WhatIfIn(BaseModel):
    milestone_id: int
    days: int = Field(ge=1, le=rebuild_schedule.MAX_DELAY_DAYS)


class DelayIn(WhatIfIn):
    reason: str = Field(min_length=3, max_length=300)


class WhatIfOut(BaseModel):
    milestone_id: int
    days: int
    slack_days: int  # how much of the delay the plan absorbs before move-in moves
    move_in_before: datetime
    move_in_after: datetime
    move_in_days: int
    moved: list[dict]


class ProjectOut(ORM):
    id: int
    title: str
    status: str
    total_price: Money
    household_name: str
    contractor: ContractorOut
    deposit_cap: Money
    escrow_balance: Money
    milestones: list[MilestoneOut]
    move_in: datetime | None = None
    planned_move_in: datetime | None = None  # in the plan the homeowner accepted
    changes: list[ScheduleChangeOut] = []  # delays the contractor recorded, newest first


def milestone_out(m: Milestone, slack: dict[int, int] | None = None) -> MilestoneOut:
    out = MilestoneOut.model_validate(m)
    out.photo_urls = [media_url(mid) for mid in m.photo_media_ids]
    out.needs_human_review = m.status == "submitted" and rebuild.needs_human_review(m)
    out.after = rebuild_schedule.predecessors(m)
    out.slack_days = (slack or {}).get(m.id)
    return out


def change_out(c: ScheduleChange) -> ScheduleChangeOut:
    return ScheduleChangeOut(
        id=c.id,
        milestone_id=c.milestone_id,
        milestone_title=c.milestone.title,
        days=c.days,
        reason=c.reason,
        moved=c.moved,
        move_in_before=c.move_in_before,
        move_in_after=c.move_in_after,
        created_at=c.created_at,
    )


def project_out(db: Session, p: RebuildProject) -> ProjectOut:
    slack = rebuild_schedule.slack(list(p.milestones))
    milestones = [milestone_out(m, slack) for m in p.milestones]
    return ProjectOut(
        id=p.id,
        title=p.title,
        status=p.status,
        total_price=p.total_price,
        household_name=p.household.name,
        contractor=ContractorOut.model_validate(p.contractor),
        deposit_cap=rebuild.deposit_cap(p.total_price),
        escrow_balance=rebuild.escrow_balance(db, p.id),
        milestones=milestones,
        move_in=rebuild_schedule.move_in(list(p.milestones)),
        planned_move_in=rebuild_schedule.move_in(list(p.milestones), baseline=True),
        changes=[change_out(c) for c in p.schedule_changes[:5]],
    )


def my_contractor(user: ContractorUser, db: DB) -> Contractor:
    contractor = db.scalar(select(Contractor).where(Contractor.user_id == user.id))
    if contractor is None:
        raise HTTPException(404, "No contractor profile for this account")
    return contractor


MyContractor = Annotated[Contractor, Depends(my_contractor)]


def project_for(db: Session, project_id: int, user: User) -> RebuildProject:
    """The household, its contractor and staff can see a project; nobody else."""
    p = db.get(RebuildProject, project_id)
    if p is None:
        raise HTTPException(404, "Project not found")
    allowed = (
        user.household_id == p.household_id
        or p.contractor.user_id == user.id
        or user.role in {Role.REVIEWER, Role.SUPERVISOR, Role.ORG_ADMIN}
    )
    if not allowed:
        raise HTTPException(404, "Project not found")
    return p


def milestone_for(db: Session, milestone_id: int, user: User) -> Milestone:
    m = db.get(Milestone, milestone_id)
    if m is None:
        raise HTTPException(404, "Milestone not found")
    project_for(db, m.project_id, user)
    return m


def run(fn, *args):
    try:
        return fn(*args)
    except rebuild.RebuildError as e:
        raise HTTPException(409, str(e)) from None


@router.get("/contractors", response_model=list[ContractorOut])
def list_contractors(user: CurrentUser, db: DB) -> list[Contractor]:
    return list(db.scalars(select(Contractor).where(Contractor.license_verified).order_by(Contractor.business_name)))


@router.post("/households/me/projects", response_model=ProjectOut, status_code=201)
def start_project(body: ProjectIn, home: MyHousehold, db: DB) -> ProjectOut:
    contractor = db.get(Contractor, body.contractor_id)
    if contractor is None or not contractor.license_verified:
        raise HTTPException(404, "Contractor not found")
    p = RebuildProject(household_id=home.id, contractor_id=contractor.id, title=body.title)
    db.add(p)
    db.commit()
    return project_out(db, p)


@router.get("/households/me/projects", response_model=list[ProjectOut])
def my_projects(home: MyHousehold, db: DB) -> list[ProjectOut]:
    ps = db.scalars(select(RebuildProject).where(RebuildProject.household_id == home.id).order_by(RebuildProject.id))
    return [project_out(db, p) for p in ps]


@router.get("/contractors/me/projects", response_model=list[ProjectOut])
def contractor_projects(contractor: MyContractor, db: DB) -> list[ProjectOut]:
    ps = db.scalars(
        select(RebuildProject).where(RebuildProject.contractor_id == contractor.id).order_by(RebuildProject.id)
    )
    return [project_out(db, p) for p in ps]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, user: CurrentUser, db: DB) -> ProjectOut:
    return project_out(db, project_for(db, project_id, user))


@router.put("/projects/{project_id}/plan", response_model=ProjectOut)
def submit_plan(project_id: int, body: PlanIn, contractor: MyContractor, user: ContractorUser, db: DB) -> ProjectOut:
    p = project_for(db, project_id, user)
    if p.contractor_id != contractor.id:
        raise HTTPException(404, "Project not found")
    return project_out(db, run(rebuild.submit_plan, db, p, [m.model_dump() for m in body.milestones], user))


@router.post("/projects/{project_id}/accept", response_model=ProjectOut)
def accept_plan(project_id: int, home: MyHousehold, user: CurrentUser, db: DB) -> ProjectOut:
    p = project_for(db, project_id, user)
    if p.household_id != home.id:
        raise HTTPException(404, "Project not found")
    return project_out(db, run(rebuild.accept_plan, db, p, user))


@router.post("/milestones/{milestone_id}/submit", response_model=MilestoneOut)
def submit_milestone(
    milestone_id: int, contractor: MyContractor, user: ContractorUser, db: DB, files: list[UploadFile] | None = None
) -> MilestoneOut:
    m = milestone_for(db, milestone_id, user)
    if m.project.contractor_id != contractor.id:
        raise HTTPException(404, "Milestone not found")
    media = []
    for upload in (files or [])[:8]:
        try:
            img = prepare_image(upload.file.read())
        except InvalidImage as e:
            raise HTTPException(422, f"{upload.filename}: {e}") from None
        media.append(
            Media(
                household_id=m.project.household_id,
                content_type="image/jpeg",
                data=img.jpeg,
                width=img.width,
                height=img.height,
                sha256=img.sha256,
                phash=img.phash,
                captured_at=img.captured_at,
                kind="site_photo",
            )
        )
    db.add_all(media)
    db.flush()
    return milestone_out(run(rebuild.submit_milestone, db, m, media, user))


@router.post("/milestones/{milestone_id}/approve", response_model=MilestoneOut)
def approve_milestone(milestone_id: int, home: MyHousehold, user: CurrentUser, db: DB) -> MilestoneOut:
    m = milestone_for(db, milestone_id, user)
    if m.project.household_id != home.id:
        raise HTTPException(404, "Milestone not found")
    return milestone_out(run(rebuild.approve_milestone, db, m, user))


@router.post("/milestones/{milestone_id}/dispute", response_model=MilestoneOut)
def dispute_milestone(milestone_id: int, body: DisputeIn, home: MyHousehold, user: CurrentUser, db: DB) -> MilestoneOut:
    m = milestone_for(db, milestone_id, user)
    if m.project.household_id != home.id:
        raise HTTPException(404, "Milestone not found")
    return milestone_out(run(rebuild.dispute_milestone, db, m, user, body.reason))


def _contractors_project(db: Session, project_id: int, contractor: Contractor, user: User) -> RebuildProject:
    p = project_for(db, project_id, user)
    if p.contractor_id != contractor.id:
        raise HTTPException(404, "Project not found")
    return p


def _step(p: RebuildProject, milestone_id: int) -> Milestone:
    m = next((m for m in p.milestones if m.id == milestone_id), None)
    if m is None:
        raise HTTPException(404, "Milestone not found")
    return m


@router.post("/projects/{project_id}/what-if", response_model=WhatIfOut)
def what_if(project_id: int, body: WhatIfIn, contractor: MyContractor, user: ContractorUser, db: DB) -> WhatIfOut:
    """What moves if a step runs late, before the contractor tells the homeowner. Nothing is saved."""
    p = _contractors_project(db, project_id, contractor, user)
    m = _step(p, body.milestone_id)
    try:
        result = rebuild_schedule.what_if(p, m, body.days)
    except rebuild_schedule.ScheduleError as e:
        raise HTTPException(409, str(e)) from None
    return WhatIfOut(
        milestone_id=m.id,
        days=body.days,
        slack_days=rebuild_schedule.slack(list(p.milestones)).get(m.id, 0),
        move_in_before=result.move_in_before,
        move_in_after=result.move_in_after,
        move_in_days=result.move_in_days,
        moved=[mv.as_dict() for mv in result.moves],
    )


@router.post("/projects/{project_id}/delays", response_model=ScheduleChangeOut, status_code=201)
def record_delay(
    project_id: int, body: DelayIn, contractor: MyContractor, user: ContractorUser, db: DB
) -> ScheduleChangeOut:
    """The contractor records a delay: the late step and the steps after it move, and the homeowner is told why."""
    p = _contractors_project(db, project_id, contractor, user)
    m = _step(p, body.milestone_id)
    try:
        change = rebuild_schedule.record_delay(db, p, m, body.days, body.reason, user)
    except rebuild_schedule.ScheduleError as e:
        raise HTTPException(409, str(e)) from None
    return change_out(change)
