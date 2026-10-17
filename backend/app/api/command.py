"""Command Center endpoints for relief-organization staff."""

from collections import Counter
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, aid_batches, command
from app import ask_grid as ask_grid_module
from app.auth import require_role
from app.db import get_db
from app.models import AidBatch, Role, User
from app.schemas import Money

router = APIRouter(tags=["command"])
DB = Annotated[Session, Depends(get_db)]
# Every household's details are visible here, so only organization staff who run the response.
OrgStaff = Annotated[User, Depends(require_role(Role.ORG_ADMIN, Role.SUPERVISOR))]


@router.post("/command/households/rows")
def household_rows(staff: OrgStaff, db: DB, req: Annotated[dict, Body()]) -> dict:
    """AG Grid server-side row model: one block of household rows or group rows."""
    try:
        return command.rows(db, req)
    except command.BadRequest as e:
        raise HTTPException(422, str(e)) from None


@router.get("/command/households/values/{field}")
def household_values(field: str, staff: OrgStaff, db: DB) -> list:
    try:
        return command.set_values(db, field)
    except command.BadRequest as e:
        raise HTTPException(404, str(e)) from None


@router.get("/command/summary")
def command_summary(staff: OrgStaff, db: DB) -> dict:
    return command.summary(db)


# --- Batch cash aid (two-person approval) ---------------------------------------------------------


class BatchRuleIn(BaseModel):
    filter_model: dict = Field(default_factory=dict)
    amounts: dict[str, Decimal] = Field(default_factory=lambda: dict(aid_batches.DEFAULT_AMOUNTS))


class BatchIn(BatchRuleIn):
    title: str = Field(min_length=3, max_length=200)


class RejectIn(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class BatchItemOut(BaseModel):
    household_id: int
    household_name: str
    damage_level: str
    amount: Money
    receiver: str
    status: str
    note: str | None


class BatchOut(BaseModel):
    id: int
    title: str
    status: str
    total_amount: Money
    households: int
    status_counts: dict[str, int]
    created_by: str
    decided_by: str | None
    decision_note: str | None
    error: str | None
    paypal_batch_id: str | None
    created_at: datetime
    decided_at: datetime | None
    rule: dict
    can_decide: bool
    items: list[BatchItemOut] | None = None


def mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}"


def batch_out(batch: AidBatch, viewer: User, with_items: bool = False) -> BatchOut:
    paid = [i for i in batch.items if i.status != "skipped"]
    return BatchOut(
        id=batch.id,
        title=batch.title,
        status=batch.status,
        total_amount=batch.total_amount,
        households=len(paid),
        status_counts=dict(Counter(i.status for i in batch.items)),
        created_by=batch.created_by.name,
        decided_by=batch.decided_by.name if batch.decided_by else None,
        decision_note=batch.decision_note,
        error=batch.error,
        paypal_batch_id=batch.paypal_batch_id,
        created_at=batch.created_at,
        decided_at=batch.decided_at,
        rule=batch.rule,
        can_decide=batch.status in aid_batches.OPEN and batch.created_by_user_id != viewer.id,
        items=[
            BatchItemOut(
                household_id=i.household_id,
                household_name=i.household.name,
                damage_level=i.household.damage_level,
                amount=i.amount,
                receiver=mask(i.receiver),
                status=i.status,
                note=i.note,
            )
            for i in batch.items
        ]
        if with_items
        else None,
    )


def get_batch(db: Session, batch_id: int) -> AidBatch:
    batch = db.get(AidBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "Batch not found")
    return batch


def run(fn, *args):
    try:
        return fn(*args)
    except (aid_batches.BatchError, command.BadRequest) as e:
        raise HTTPException(409, str(e)) from None


@router.post("/command/batches/preview")
def preview_batch(body: BatchRuleIn, staff: OrgStaff, db: DB) -> dict:
    return run(aid_batches.preview, db, body.filter_model, body.amounts)


@router.post("/command/batches", response_model=BatchOut, status_code=201)
def create_batch(body: BatchIn, staff: OrgStaff, db: DB) -> BatchOut:
    batch = run(aid_batches.create, db, staff, body.title, body.filter_model, body.amounts)
    return batch_out(batch, staff)


@router.get("/command/batches", response_model=list[BatchOut])
def list_batches(staff: OrgStaff, db: DB) -> list[BatchOut]:
    return [batch_out(b, staff, with_items=True) for b in db.scalars(select(AidBatch).order_by(AidBatch.id.desc()))]


@router.post("/command/batches/{batch_id}/approve", response_model=BatchOut)
def approve_batch(batch_id: int, staff: OrgStaff, db: DB) -> BatchOut:
    return batch_out(run(aid_batches.approve, db, get_batch(db, batch_id), staff), staff, with_items=True)


@router.post("/command/batches/{batch_id}/reject", response_model=BatchOut)
def reject_batch(batch_id: int, body: RejectIn, staff: OrgStaff, db: DB) -> BatchOut:
    return batch_out(run(aid_batches.reject, db, get_batch(db, batch_id), staff, body.reason), staff, with_items=True)


@router.post("/command/batches/{batch_id}/refresh", response_model=BatchOut)
def refresh_batch(batch_id: int, staff: OrgStaff, db: DB) -> BatchOut:
    return batch_out(run(aid_batches.refresh, db, get_batch(db, batch_id)), staff, with_items=True)


# --- Ask the grid (AG Grid AI Toolkit) -------------------------------------------------------------


class AskIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    grid_schema: dict  # api.getStructuredSchema() from the browser


@router.post("/command/ask")
def ask_grid(body: AskIn, staff: OrgStaff, db: DB) -> dict:
    try:
        return ask_grid_module.ask(db, body.question, body.grid_schema)
    except ask_grid_module.Unsupported as e:
        raise HTTPException(422, str(e)) from None
    except ai.AIError:
        raise HTTPException(
            503, "The assistant couldn't answer right now. Try again, or use the column filters."
        ) from None
