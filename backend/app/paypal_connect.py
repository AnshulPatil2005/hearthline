"""Connect a person's own PayPal account (Log in with PayPal), so the money they receive goes to an account PayPal
says is theirs: a household's cash aid, a contractor's milestone payments, a business's Reopen Fund releases.

The round trip carries a signed, short-lived `state` tied to the signed-in user, so a code can't be replayed into
someone else's account. Changing the account is recorded in the audit log (old and new address, masked).
"""

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.config import get_settings
from app.models import Business, Contractor, PayPalLink, Role, User, now
from app.paypal import identity
from app.paypal.rest import PayPalError

STATE_MINUTES = 15
PURPOSE = "paypal_connect"


class ConnectError(ValueError):
    pass


def redirect_uri() -> str:
    s = get_settings()
    return s.paypal_connect_return_url or f"{s.web_url}/connect/paypal"


def mask(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    name, domain = email.split("@", 1)
    return f"{name[:2]}{'•' * max(1, len(name) - 2)}@{domain}"


def start(user: User) -> str:
    """The PayPal sign-in page to send this user to."""
    state = jwt.encode(
        {
            "sub": str(user.id),
            "purpose": PURPOSE,
            "n": secrets.token_urlsafe(8),
            "exp": datetime.now(UTC) + timedelta(minutes=STATE_MINUTES),
        },
        get_settings().secret_key,
        algorithm="HS256",
    )
    return identity.authorize_url(state, redirect_uri())


def _check_state(state: str, user: User) -> None:
    try:
        claims = jwt.decode(state, get_settings().secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError as e:
        raise ConnectError("That PayPal sign-in took too long. Please try again.") from e
    except jwt.PyJWTError as e:
        raise ConnectError("That PayPal sign-in link isn't valid. Please try again.") from e
    if claims.get("purpose") != PURPOSE or claims.get("sub") != str(user.id):
        raise ConnectError("That PayPal sign-in was started by someone else. Please try again.")


@dataclass
class Receives:
    what: str  # cash_aid | milestone_payments | reopen_releases
    current: str | None  # where that money goes now (masked)


def _targets(db: Session, user: User) -> list[tuple[str, object]]:
    """What this user is paid for, and the record that holds the payout address."""
    found: list[tuple[str, object]] = []
    if user.role == Role.HOUSEHOLD and user.household is not None:
        found.append(("cash_aid", user.household))
    if user.role == Role.CONTRACTOR:
        contractor = db.scalar(select(Contractor).where(Contractor.user_id == user.id))
        if contractor is not None:
            found.append(("milestone_payments", contractor))
    if user.role == Role.BUSINESS:
        for business in db.scalars(select(Business).where(Business.owner_user_id == user.id)):
            found.append(("reopen_releases", business))
    return found


def receives(db: Session, user: User) -> list[Receives]:
    return [Receives(what, mask(getattr(record, "payout_email", None))) for what, record in _targets(db, user)]


def link_for(db: Session, user: User) -> PayPalLink | None:
    return db.scalar(select(PayPalLink).where(PayPalLink.user_id == user.id))


def finish(db: Session, user: User, code: str, state: str) -> PayPalLink:
    """PayPal sent the person back with a code: learn their PayPal account and pay them there from now on."""
    _check_state(state, user)
    if not _targets(db, user):
        raise ConnectError("Only households, contractors and businesses receive money through Hearthline.")
    try:
        person = identity.exchange(code)
    except PayPalError as e:
        raise ConnectError("PayPal didn't accept that sign-in. Please try again.") from e
    if not person.email:
        raise ConnectError("PayPal didn't share the account's email address, so we can't send money to it.")
    link = link_for(db, user) or PayPalLink(user_id=user.id, payer_id=person.payer_id, email=person.email)
    link.payer_id, link.email, link.name = person.payer_id, person.email, person.name[:160]
    link.verified_account, link.connected_at = person.verified, now()
    db.add(link)
    changed = []
    for what, record in _targets(db, user):
        before = record.payout_email
        if before != person.email:
            record.payout_email = person.email
            changed.append({"for": what, "from": mask(before), "to": mask(person.email)})
    audit.record(
        db,
        actor_user_id=user.id,
        action="paypal.connected",
        subject_type="user",
        subject_id=user.id,
        data={"payer_id": person.payer_id, "verified_account": person.verified, "changed": changed},
    )
    db.commit()
    return link
