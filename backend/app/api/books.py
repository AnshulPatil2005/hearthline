"""The relief fund's books against PayPal's (Transaction Search through APIMatic's PayPal SDK). Staff only."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import reconcile
from app.auth import require_role
from app.db import get_db
from app.models import Role, User
from app.paypal import reporting
from app.schemas import Money

router = APIRouter(prefix="/command/books", tags=["books"])
DB = Annotated[Session, Depends(get_db)]
OrgStaff = Annotated[User, Depends(require_role(Role.ORG_ADMIN, Role.SUPERVISOR))]


class BalanceOut(BaseModel):
    available: Money
    total: Money
    as_of: datetime | None


@router.get("/balance", response_model=BalanceOut)
def paypal_balance(staff: OrgStaff) -> BalanceOut:
    """What the relief fund holds at PayPal (PayPal refreshes it with a delay of up to three hours)."""
    try:
        bal = reporting.balance()
    except reporting.ReportingError as e:
        raise HTTPException(e.status_code, str(e)) from e
    return BalanceOut(available=bal.available, total=bal.total, as_of=bal.as_of)


class LineOut(BaseModel):
    status: Literal["matched", "amount_differs", "not_in_books", "missing_at_paypal", "waiting", "info"]
    direction: Literal["in", "out", "refund", "other"]
    amount: Money
    at: datetime | None
    paypal_id: str | None
    hearthline: str | None
    note: str


class ReportOut(BaseModel):
    start: datetime
    end: datetime
    paypal_refreshed_at: datetime | None
    counts: dict[str, int]
    paypal_in: Money
    paypal_out: Money
    lines: list[LineOut]


@router.get("/reconcile", response_model=ReportOut)
def reconcile_books(staff: OrgStaff, db: DB) -> ReportOut:
    """Every payout traced to an approved decision, every payment received found in our books."""
    try:
        report = reconcile.build(db)
    except reporting.ReportingError as e:
        raise HTTPException(e.status_code, str(e)) from e
    statuses = ("matched", "amount_differs", "not_in_books", "missing_at_paypal", "waiting", "info")
    money_lines = [line for line in report.lines if line.paypal_id and line.direction != "other"]
    return ReportOut(
        start=report.start,
        end=report.end,
        paypal_refreshed_at=report.paypal_refreshed_at,
        counts={s: report.count(s) for s in statuses},
        paypal_in=sum((line.amount for line in money_lines if line.amount > 0), Decimal(0)),
        paypal_out=-sum((line.amount for line in money_lines if line.amount < 0), Decimal(0)),
        lines=[LineOut(**vars(line)) for line in report.lines],
    )
