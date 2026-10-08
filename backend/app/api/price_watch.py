"""Price Watch: public report of essential prices against their pre-disaster baseline."""

from datetime import date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import gouging
from app.auth import require_role
from app.db import get_db
from app.models import DisasterEvent, PriceWatch, Role, User
from app.schemas import Money

router = APIRouter(tags=["price watch"])
DB = Annotated[Session, Depends(get_db)]
OrgStaff = Annotated[User, Depends(require_role(Role.ORG_ADMIN, Role.SUPERVISOR))]
SPARK_DAYS = 60


class EventOut(BaseModel):
    name: str
    declared_at: datetime
    protection_until: datetime
    protection_active: bool
    limit_percent: float


class WatchOut(BaseModel):
    id: int
    title: str
    seller: str
    category: str
    source: str
    url: str | None
    baseline_price: Money | None
    current_price: Money | None
    markup_percent: float | None
    status: str
    checked_at: datetime | None
    history: list[float]  # one price per day for the last 60 days (gaps carry the previous price)


class PriceWatchOut(BaseModel):
    event: EventOut
    rows: list[WatchOut]


def _event(db: Session) -> DisasterEvent:
    event = db.scalar(select(DisasterEvent).where(DisasterEvent.status == "active").order_by(DisasterEvent.id))
    if event is None:
        raise HTTPException(404, "No active disaster")
    return event


def _daily(watch: PriceWatch) -> list[float]:
    prices = {s.observed_on: float(s.price) for s in watch.snapshots}
    if not prices:
        return []
    out, last = [], None
    for i in range(SPARK_DAYS, -1, -1):
        day = date.today() - timedelta(days=i)
        last = prices.get(day, last)
        if last is not None:
            out.append(last)
    return out


@router.get("/price-watch", response_model=PriceWatchOut)
def price_watch(db: DB) -> PriceWatchOut:
    event = _event(db)
    declared = gouging._aware(event.declared_at)
    watches = db.scalars(select(PriceWatch).where(PriceWatch.disaster_event_id == event.id).order_by(PriceWatch.id))
    return PriceWatchOut(
        event=EventOut(
            name=event.name,
            declared_at=declared,
            protection_until=event.price_protection_until or declared + timedelta(days=30),
            protection_active=gouging.protection_active(event),
            limit_percent=gouging.LIMIT_PERCENT,
        ),
        rows=[
            WatchOut(
                id=w.id,
                title=w.title,
                seller=w.seller,
                category=w.category,
                source=w.source,
                url=w.url,
                baseline_price=w.baseline_price,
                current_price=w.current_price,
                markup_percent=w.markup_percent,
                status=w.status,
                checked_at=w.checked_at,
                history=_daily(w),
            )
            for w in watches
        ],
    )


@router.post("/command/price-watch/refresh")
def refresh(staff: OrgStaff, db: DB) -> dict:
    """Pull fresh Channel3 price history for tracked online products."""
    return {"refreshed": gouging.refresh(db, _event(db))}
