"""Hazard alerts from the US National Weather Service (free, no key).

There are no cron jobs on Render's free tier, so alerts are fetched on demand when a household
opens Hearthline, at most once every 10 minutes per household.
"""

import time
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alert, Household

NWS_ALERTS = "https://api.weather.gov/alerts/active"
# NWS asks every client to identify itself.
HEADERS = {"User-Agent": "Hearthline/0.1 (disaster-recovery hackathon demo)", "Accept": "application/geo+json"}
REFRESH_SECONDS = 600
_last_fetch: dict[int, float] = {}


def _parse_time(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def refresh_from_nws(db: Session, home: Household) -> None:
    if home.lat is None or time.monotonic() - _last_fetch.get(home.id, -REFRESH_SECONDS) < REFRESH_SECONDS:
        return
    _last_fetch[home.id] = time.monotonic()
    try:
        r = httpx.get(NWS_ALERTS, params={"point": f"{home.lat:.4f},{home.lng:.4f}"}, headers=HEADERS, timeout=10)
        r.raise_for_status()
        features = r.json().get("features", [])
    except (httpx.HTTPError, ValueError):
        return  # alerts are best-effort; never block the dashboard on the weather service
    for feature in features:
        props = feature["properties"]
        external_id = props["id"]
        if db.scalar(select(Alert.id).where(Alert.household_id == home.id, Alert.external_id == external_id)):
            continue
        db.add(
            Alert(
                household_id=home.id,
                source="nws",
                external_id=external_id,
                event=props.get("event") or "Alert",
                headline=props.get("headline") or props.get("event") or "",
                severity=props.get("severity") or "Unknown",
                description=(props.get("description") or "")[:4000],
                instruction=(props.get("instruction") or "")[:2000],
                effective=_parse_time(props.get("effective")),
                expires=_parse_time(props.get("expires")),
            )
        )
    db.commit()


def simulate_evacuation_warning(db: Session, home: Household) -> Alert:
    """A realistic NWS-style alert for demos, so judges can see the alert flow on any day."""
    now = datetime.now(UTC)
    place = home.disaster_event.name if home.disaster_event else f"{home.city} area"
    alert = Alert(
        household_id=home.id,
        source="simulated",
        external_id=f"simulated-{home.id}-{int(now.timestamp())}",
        event="Evacuation Warning",
        headline=f"Evacuation Warning issued for {home.city}, {home.state} due to the {place}",
        severity="Severe",
        description=(
            f"Fire activity near {home.city} is increasing. Strong winds may push the fire toward homes "
            "in the warning area. Be ready to leave at short notice."
        ),
        instruction="Prepare to leave now. Gather essential items and keep your phone charged. "
        "Leave immediately if an evacuation order is issued.",
        effective=now,
        expires=now + timedelta(hours=12),
    )
    db.add(alert)
    db.commit()
    return alert
