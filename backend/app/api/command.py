"""Command Center endpoints for relief-organization staff."""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app import command
from app.auth import require_role
from app.db import get_db
from app.models import Role, User

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
