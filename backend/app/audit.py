"""Tamper-evident audit log. Each event's hash covers its content and the previous event's hash,
so editing or deleting any past event breaks every hash after it (detected by `verify_chain`)."""

import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent

GENESIS = "0" * 64


def _digest(prev_hash: str, actor: int | None, action: str, subject_type: str, subject_id: str, data: dict) -> str:
    body = json.dumps(
        {"prev": prev_hash, "actor": actor, "action": action, "type": subject_type, "id": subject_id, "data": data},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def record(
    db: Session,
    *,
    action: str,
    subject_type: str,
    subject_id: str | int,
    data: dict | None = None,
    actor_user_id: int | None = None,
) -> AuditEvent:
    last = db.scalar(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(1))
    prev_hash = last.hash if last else GENESIS
    data = json.loads(json.dumps(data or {}, default=str))  # store exactly what was hashed
    event = AuditEvent(
        actor_user_id=actor_user_id,
        action=action,
        subject_type=subject_type,
        subject_id=str(subject_id),
        data=data,
        prev_hash=prev_hash,
        hash=_digest(prev_hash, actor_user_id, action, subject_type, str(subject_id), data),
    )
    db.add(event)
    db.flush()
    return event


def verify_chain(db: Session) -> tuple[bool, int | None]:
    """(True, None) if intact, else (False, id of the first broken event)."""
    prev_hash = GENESIS
    for event in db.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        expected = _digest(
            prev_hash, event.actor_user_id, event.action, event.subject_type, event.subject_id, event.data
        )
        if event.prev_hash != prev_hash or event.hash != expected:
            return False, event.id
        prev_hash = event.hash
    return True, None
