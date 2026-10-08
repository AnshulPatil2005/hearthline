"""Impact: a donor's gifts and where they went; the relief organization's grant report (JSON and PDF)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import grant_pdf, impact
from app.auth import CurrentUser, require_role
from app.config import get_settings
from app.db import get_db
from app.models import DisasterEvent, Role, User

router = APIRouter(tags=["impact"])
DB = Annotated[Session, Depends(get_db)]
OrgStaff = Annotated[User, Depends(require_role(Role.ORG_ADMIN, Role.SUPERVISOR))]


@router.get("/donors/me/giving", response_model=impact.Giving)
def my_giving(user: CurrentUser, db: DB) -> impact.Giving:
    return impact.giving(db, user, get_settings().web_url)


class GivingNote(BaseModel):
    summary: str
    by_ai: bool


@router.get("/donors/me/giving/note", response_model=GivingNote)
def my_giving_note(user: CurrentUser, db: DB) -> GivingNote:
    """The Funds agent's short note about where the donor's gifts went (cached until something changes)."""
    g = impact.giving(db, user, get_settings().web_url, with_ai=True)
    return GivingNote(summary=g.summary, by_ai=g.summary_by_ai)


class GrantReport(BaseModel):
    numbers: dict
    narrative: impact.Narrative
    narrative_by_ai: bool


def _event(db: Session) -> DisasterEvent:
    event = db.scalar(select(DisasterEvent).where(DisasterEvent.status == "active").order_by(DisasterEvent.id))
    if event is None:
        raise HTTPException(404, "No active disaster")
    return event


@router.get("/command/reports/grant", response_model=GrantReport)
def grant_report(staff: OrgStaff, db: DB) -> GrantReport:
    numbers = impact.report_numbers(db, _event(db))
    narrative, by_ai = impact.grant_narrative(numbers)
    return GrantReport(numbers=numbers, narrative=narrative, narrative_by_ai=by_ai)


@router.get("/command/reports/grant.pdf")
def grant_report_pdf(staff: OrgStaff, db: DB) -> Response:
    numbers = impact.report_numbers(db, _event(db))
    narrative, by_ai = impact.grant_narrative(numbers)
    pdf = grant_pdf.build(numbers, narrative, staff.name, by_ai)
    name = f"hearthline-grant-report-{date.today().isoformat()}.pdf"
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )
