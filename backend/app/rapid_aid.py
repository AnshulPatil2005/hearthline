"""First-72-hours aid: emergency cash for households that prepared, within hours of an official warning.

When an official warning (the National Weather Service) or a disaster declaration covers a disaster's zone, a trigger
is proposed. One staff member approves it: Hearthline prepares a cash-aid batch under its own account, by fixed
rules, and the person's approval pays it through the batch path (re-checks, one PayPal Payouts call, the ledger), so
rules prepare and a person decides, as for every batch. Who gets it: households in the zone that prepared before the
disaster (verified residence, an inventory on file, so verification level 3) with a PayPal account. Sentinel holds
back anyone with warning signs for a person to check. Approving also starts a round of donors' giving mandates.
"""

import logging
import threading
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import aid_batches, audit, geo, mandates, trust
from app.alerts import HEADERS, NWS_ALERTS
from app.db import SessionLocal
from app.models import AidBatch, AidBatchItem, DisasterEvent, Household, RapidAidTrigger, Role, User, now

log = logging.getLogger(__name__)

PREPARED = 3  # verified residence plus an inventory scanned before the disaster
BASE = Decimal("250")
PER_PERSON = Decimal("50")
CAP = Decimal("500")
# Warnings that mean people may have to leave now. NWS severities: Extreme, Severe, Moderate, Minor, Unknown.
QUALIFYING = {
    "Evacuation Order",
    "Evacuation Warning",
    "Evacuation - Immediate",
    "Fire Warning",
    "Flash Flood Emergency",
    "Flash Flood Warning",
    "Hurricane Warning",
    "Storm Surge Warning",
    "Tornado Warning",
    "Extreme Wind Warning",
    "Tsunami Warning",
    "Earthquake Warning",
}
SYSTEM_EMAIL = "rapid-aid@hearthline.app"


class RapidAidError(ValueError):
    pass


@dataclass(frozen=True)
class Planned:
    household_id: int
    name: str
    amount: Decimal
    receiver: str


@dataclass(frozen=True)
class Held:
    household_id: int
    name: str
    reason: str  # Sentinel's first warning sign


def amount_for(household_size: int) -> Decimal:
    return min(BASE + PER_PERSON * max(household_size - 1, 0), CAP)


def _system_user(db: Session) -> User:
    """The account Hearthline prepares rule-based batches under; it can't sign in and can't approve anything."""
    user = db.scalar(select(User).where(User.email == SYSTEM_EMAIL))
    if user is None:
        user = User(email=SYSTEM_EMAIL, name="Hearthline (first-72-hours rules)", role=Role.ORG_ADMIN)
        db.add(user)
        db.flush()
    return user


def _propose(db: Session, disaster: DisasterEvent, **fields: object) -> RapidAidTrigger | None:
    """Record a trigger once per warning (the unique constraint refuses a repeat)."""
    trigger = RapidAidTrigger(disaster_event_id=disaster.id, **fields)
    db.add(trigger)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    audit.record(
        db,
        actor_user_id=None,
        action="rapid_aid.proposed",
        subject_type="rapid_aid_trigger",
        subject_id=trigger.id,
        data={"source": trigger.source, "event": trigger.event, "disaster": disaster.name},
    )
    db.commit()
    return trigger


def check_official(db: Session, event: DisasterEvent) -> list[RapidAidTrigger]:
    """Ask the National Weather Service what's active at the zone; propose aid for each qualifying warning."""
    lat, lng = geo.center(event.zone)
    try:
        r = httpx.get(NWS_ALERTS, params={"point": f"{lat:.4f},{lng:.4f}"}, headers=HEADERS, timeout=10)
        r.raise_for_status()
        features = r.json().get("features", [])
    except (httpx.HTTPError, ValueError) as e:
        raise RapidAidError("The National Weather Service didn't answer; try again in a minute") from e
    proposed = []
    for feature in features:
        props = feature.get("properties") or {}
        if props.get("event") not in QUALIFYING or props.get("severity") not in ("Extreme", "Severe"):
            continue
        sent = props.get("sent") or props.get("effective")
        trigger = _propose(
            db,
            event,
            source="nws",
            external_id=props["id"],
            event=props["event"],
            headline=(props.get("headline") or props["event"])[:500],
            severity=props["severity"],
            issued_at=datetime.fromisoformat(sent) if sent else now(),
        )
        if trigger:
            proposed.append(trigger)
    return proposed


def simulate(db: Session, event: DisasterEvent) -> RapidAidTrigger:
    """An NWS-style evacuation order for demos, so the flow can be seen on any day. Marked as simulated."""
    at = datetime.now(UTC)
    trigger = _propose(
        db,
        event,
        source="simulated",
        external_id=f"simulated-{event.id}-{int(at.timestamp())}",
        event="Evacuation Order",
        headline=f"Evacuation Order for the {event.name} area: leave now (simulated for this demo)",
        severity="Extreme",
        issued_at=at,
    )
    if trigger is None:
        raise RapidAidError("A simulated order was just made; try again in a second")
    return trigger


def declared(db: Session, event: DisasterEvent, number: str, title: str) -> RapidAidTrigger | None:
    """A disaster declaration (e.g. FEMA's) covering the zone."""
    return _propose(
        db,
        event,
        source="declaration",
        external_id=f"declaration-{number}",
        event=title[:120],
        headline=f"{title} declared for the {event.name} area"[:500],
        severity="Extreme",
    )


def plan(db: Session, trigger: RapidAidTrigger) -> tuple[list[Planned], list[Held], Counter]:
    """Who would be paid now, who Sentinel holds for a person to check, and how many were left out, by reason."""
    homes = db.scalars(
        select(Household).where(Household.disaster_event_id == trigger.disaster_event_id).order_by(Household.id)
    )
    shared, recent, in_batch = (
        aid_batches._shared_paypal(db),
        aid_batches._recent_aid(db),
        aid_batches._in_open_batch(db),
    )
    paid, held, left_out = [], [], Counter()
    for home in homes:
        if home.verification_level < PREPARED:
            left_out["not_prepared" if home.verification_level >= 2 else "not_verified"] += 1
            continue
        reason = aid_batches._exclusion(home.verification_level, home.payout_email, home.id, shared, recent, in_batch)
        if reason:
            left_out[reason] += 1
            continue
        amount = amount_for(home.household_size)
        flags = trust.sentinel_flags(db, home, claim_amount=amount)
        _, tier = trust.risk(flags)
        if tier != "low":
            held.append(Held(home.id, home.name, flags[0].message if flags else "Needs a person to check"))
            continue
        paid.append(Planned(home.id, home.name, amount, home.payout_email or ""))
    return paid, held, left_out


def approve(db: Session, trigger: RapidAidTrigger, staff: User) -> RapidAidTrigger:
    """One person approves the trigger: the rules prepare the batch, and the person's approval pays it."""
    if trigger.status != "proposed":
        raise RapidAidError(f"This trigger is already {trigger.status}")
    paid, held, left_out = plan(db, trigger)
    if not paid:
        raise RapidAidError("No prepared household in the zone can be paid right now")
    system = _system_user(db)
    batch = AidBatch(
        title=f"First-72-hours aid: {trigger.disaster.name}",
        created_by_user_id=system.id,
        rule={
            "rapid_aid_trigger": trigger.id,
            "amounts": {"base": str(BASE), "per_person": str(PER_PERSON), "cap": str(CAP)},
            "held_for_review": [{"household_id": h.household_id, "name": h.name, "reason": h.reason} for h in held],
        },
        total_amount=sum((p.amount for p in paid), Decimal(0)),
    )
    batch.items = [AidBatchItem(household_id=p.household_id, amount=p.amount, receiver=p.receiver) for p in paid]
    db.add(batch)
    db.flush()
    trigger.aid_batch_id = batch.id
    trigger.status, trigger.decided_by_user_id, trigger.decided_at = "approved", staff.id, now()
    audit.record(
        db,
        actor_user_id=staff.id,
        action="rapid_aid.approved",
        subject_type="rapid_aid_trigger",
        subject_id=trigger.id,
        data={"households": len(paid), "held": len(held), "left_out": dict(left_out), "total": batch.total_amount},
    )
    db.commit()
    aid_batches.approve(db, batch, staff)  # re-checks each household, one Payouts call, the ledger
    db.refresh(trigger)
    start_mandate_round()
    return trigger


def start_mandate_round() -> None:
    """Donors' giving mandates get a round for the new emergency, in the background (tests replace this)."""
    threading.Thread(target=_give_through_mandates, daemon=True).start()


def _give_through_mandates() -> None:
    """A new emergency: donors' giving mandates get a round (in the background, with its own session)."""
    try:
        with SessionLocal() as db:
            mandates.run_all(db)
    except Exception:  # noqa: BLE001 - the aid is paid; a mandate problem is logged, never raised
        log.exception("Giving mandates after a rapid aid trigger failed")


def dismiss(db: Session, trigger: RapidAidTrigger, staff: User, note: str) -> RapidAidTrigger:
    if trigger.status != "proposed":
        raise RapidAidError(f"This trigger is already {trigger.status}")
    trigger.status, trigger.decided_by_user_id, trigger.decided_at, trigger.note = "dismissed", staff.id, now(), note
    audit.record(
        db,
        actor_user_id=staff.id,
        action="rapid_aid.dismissed",
        subject_type="rapid_aid_trigger",
        subject_id=trigger.id,
        data={"note": note},
    )
    db.commit()
    return trigger
