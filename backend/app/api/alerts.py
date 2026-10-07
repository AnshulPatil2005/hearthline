from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import alerts
from app.api.households import MyHousehold
from app.db import get_db
from app.models import Alert
from app.schemas import ORM

router = APIRouter(tags=["alerts"])
DB = Annotated[Session, Depends(get_db)]
SEVERITY_ORDER = {"Extreme": 0, "Severe": 1, "Moderate": 2, "Minor": 3}


class AlertOut(ORM):
    id: int
    source: str
    event: str
    headline: str
    severity: str
    description: str
    instruction: str
    effective: datetime | None
    expires: datetime | None


def _active(alert: Alert, now: datetime) -> bool:
    if alert.dismissed:
        return False
    if alert.expires is None:
        return True
    expires = alert.expires if alert.expires.tzinfo else alert.expires.replace(tzinfo=UTC)  # SQLite drops tz
    return expires > now


@router.get("/households/me/alerts", response_model=list[AlertOut])
def list_alerts(home: MyHousehold, db: DB) -> list[Alert]:
    """Active, undismissed alerts for the household's location (refreshes from the NWS when stale)."""
    alerts.refresh_from_nws(db, home)
    now = datetime.now(UTC)
    rows = db.scalars(select(Alert).where(Alert.household_id == home.id).order_by(Alert.created_at.desc()))
    return sorted((a for a in rows if _active(a, now)), key=lambda a: SEVERITY_ORDER.get(a.severity, 9))


@router.post("/households/me/alerts/simulate", response_model=AlertOut, status_code=201)
def simulate_alert(home: MyHousehold, db: DB) -> Alert:
    return alerts.simulate_evacuation_warning(db, home)


@router.post("/alerts/{alert_id}/dismiss", status_code=204)
def dismiss_alert(alert_id: int, home: MyHousehold, db: DB) -> None:
    alert = db.get(Alert, alert_id)
    if alert is None or alert.household_id != home.id:
        raise HTTPException(404, "Alert not found")
    alert.dismissed = True
    db.commit()
