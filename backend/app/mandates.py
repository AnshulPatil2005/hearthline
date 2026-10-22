"""Giving mandates: a donor saves their PayPal account once (PayPal Vault) and leaves a standing instruction; when
verified families in an active disaster need things the instruction covers, the giving agent gives within its limits,
with no checkout, and explains each gift. The donor can pause, resume or revoke; revoking deletes the saved account at
PayPal.

Code decides what may be given (eligible needs, the per-gift cap, what's left this month); the agent only chooses
among those and explains. Every gift is a claim first (a `mandate_gifts` row, unique per mandate and item), then a
merchant-initiated PayPal payment, then an ordinary `Donation` applied with `registry.apply_capture`, so funding, the
Shopper, the ledger, Books and the donor's impact page treat it like any other gift. See paypal-plan.md, Part 2.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import ai, audit, registry
from app.agents import giving
from app.agents.inventory import CATEGORIES as INVENTORY_CATEGORIES
from app.models import (
    DisasterEvent,
    GivingMandate,
    Household,
    MandateGift,
    Registry,
    RegistryItem,
    User,
    now,
)
from app.paypal import vault
from app.paypal.orders import Capture
from app.policy import BLOCKED_CATEGORIES

log = logging.getLogger(__name__)

CATEGORIES = sorted({c.strip() for c in INVENTORY_CATEGORIES.split(",")} - BLOCKED_CATEGORIES)
STATES = sorted(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR "
    "PA PR RI SC SD TN TX UT VT VA WA WV WI WY".split()
)
MAX_PER_GIFT = Decimal("500")
MAX_MONTHLY = Decimal("2000")
MIN_GIFT = Decimal("1")
VERIFIED = 2  # verification level a family needs before a mandate gives to them (the level cash aid needs)
MAX_NEEDS = 25  # needs shown to the agent per round


class MandateError(Exception):
    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class Round:
    gifts: list[MandateGift]
    summary: str
    by_ai: bool


def _audit(db: Session, mandate: GivingMandate, action: str, **data: object) -> None:
    audit.record(
        db,
        actor_user_id=mandate.donor_user_id,
        action=f"mandate.{action}",
        subject_type="giving_mandate",
        subject_id=mandate.id,
        data=data,
    )


def _move(db: Session, mandate: GivingMandate, *, from_: tuple[str, ...], to: str) -> bool:
    """Change the status only if it is still one of `from_`: one conditional UPDATE, so of two callers racing, the
    database lets exactly one through (paypal-plan.md, Part 2, DUPLICATE CLAIMS)."""
    moved = db.execute(
        update(GivingMandate)
        .where(GivingMandate.id == mandate.id, GivingMandate.status.in_(from_))
        .values(status=to)
        .execution_options(synchronize_session=False)
    ).rowcount
    db.commit()
    db.refresh(mandate)
    return moved == 1


# Setting up ------------------------------------------------------------------------------------------------------


def create(
    db: Session,
    donor: User,
    *,
    states: list[str],
    categories: list[str],
    per_gift_max: Decimal,
    monthly_max: Decimal,
    note: str,
    web_url: str,
) -> tuple[GivingMandate, str]:
    """A new mandate waiting for the donor to approve saving their PayPal account. Returns it and PayPal's page."""
    states = sorted({s.upper() for s in states})
    categories = sorted(set(categories))
    if bad := [s for s in states if s not in STATES]:
        raise MandateError(f"Not a US state code: {', '.join(bad)}", 422)
    if bad := [c for c in categories if c not in CATEGORIES]:
        raise MandateError(f"Not a category families can ask for: {', '.join(bad)}", 422)
    if not MIN_GIFT <= per_gift_max <= MAX_PER_GIFT:
        raise MandateError(f"Each gift can be between ${MIN_GIFT} and ${MAX_PER_GIFT}", 422)
    if not per_gift_max <= monthly_max <= MAX_MONTHLY:
        raise MandateError(f"The monthly limit must be at least one gift and at most ${MAX_MONTHLY:,}", 422)
    mandate = GivingMandate(
        donor_user_id=donor.id,
        states=states,
        categories=categories,
        per_gift_max=per_gift_max,
        monthly_max=monthly_max,
        note=note.strip()[:280],
    )
    db.add(mandate)
    db.flush()
    try:
        setup = vault.start_saving(
            f"Hearthline gives up to ${monthly_max:,.0f} a month for you after disasters",
            return_url=f"{web_url}/giving/mandate",
            cancel_url=f"{web_url}/giving/mandate?cancelled=1",
        )
    except vault.VaultError as e:
        db.rollback()
        raise MandateError(str(e), e.status_code) from e
    mandate.paypal_setup_token_id = setup.setup_id
    _audit(
        db, mandate, "created", states=states, categories=categories, per_gift_max=per_gift_max, monthly_max=monthly_max
    )
    db.commit()
    return mandate, setup.approve_url


def finish(db: Session, donor: User, setup_id: str) -> GivingMandate:
    """The donor came back from PayPal: save the account and start the mandate. Safe to call twice."""
    mandate = db.scalar(
        select(GivingMandate).where(
            GivingMandate.paypal_setup_token_id == setup_id, GivingMandate.donor_user_id == donor.id
        )
    )
    if mandate is None:
        raise MandateError("We couldn't find that giving mandate", 404)
    if not _move(db, mandate, from_=("pending",), to="saving"):
        return mandate  # already saved, or another request is saving it right now
    try:
        if not vault.setup_approved(setup_id):
            raise MandateError("PayPal hasn't confirmed that you saved your account. Try again.", 409)
        account = vault.finish_saving(setup_id)
    except (vault.VaultError, MandateError) as e:
        mandate.status, mandate.error = "pending", str(e)[:300]
        db.commit()
        raise e if isinstance(e, MandateError) else MandateError(str(e), e.status_code) from e
    mandate.paypal_payment_token_id = account.token_id
    mandate.paypal_customer_id = account.customer_id
    mandate.paypal_email = account.email
    mandate.status, mandate.error, mandate.activated_at = "active", None, now()
    _audit(db, mandate, "saved", paypal_email=account.email)
    db.commit()
    return mandate


def pause(db: Session, mandate: GivingMandate) -> GivingMandate:
    if not _move(db, mandate, from_=("active",), to="paused"):
        raise MandateError(f"This mandate is {mandate.status}", 409)
    _audit(db, mandate, "paused")
    db.commit()
    return mandate


def resume(db: Session, mandate: GivingMandate) -> GivingMandate:
    if not _move(db, mandate, from_=("paused",), to="active"):
        raise MandateError(f"This mandate is {mandate.status}", 409)
    _audit(db, mandate, "resumed")
    db.commit()
    return mandate


def revoke(db: Session, mandate: GivingMandate) -> GivingMandate:
    """Stop for good and delete the saved account at PayPal. Hearthline never gives from a revoked mandate, even if
    PayPal's delete fails (that is recorded and shown)."""
    if not _move(db, mandate, from_=("pending", "active", "paused"), to="revoked"):
        raise MandateError(f"This mandate is {mandate.status}", 409)
    mandate.revoked_at = now()
    if mandate.paypal_payment_token_id:
        try:
            vault.revoke(mandate.paypal_payment_token_id)
        except vault.VaultError as e:
            mandate.error = f"PayPal didn't confirm removing the saved account: {e}"[:300]
    _audit(db, mandate, "revoked", removed_at_paypal=mandate.error is None)
    db.commit()
    return mandate


# Giving ------------------------------------------------------------------------------------------------------------


def month_start(at: datetime | None = None) -> datetime:
    at = (at or datetime.now(UTC)).astimezone(UTC)
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def given_this_month(db: Session, mandate: GivingMandate) -> Decimal:
    """Gifts that went out (or may have) since the start of the month, UTC."""
    total = db.scalar(
        select(func.coalesce(func.sum(MandateGift.amount), 0)).where(
            MandateGift.mandate_id == mandate.id,
            MandateGift.status.in_(("given", "checking", "claimed")),
            MandateGift.created_at >= month_start(),
        )
    )
    return Decimal(total).quantize(Decimal("0.01"))


def left_this_month(db: Session, mandate: GivingMandate) -> Decimal:
    return max(mandate.monthly_max - given_this_month(db, mandate), Decimal(0))


def eligible(db: Session, mandate: GivingMandate) -> list[giving.Need]:
    """Needs this mandate may give to: open items on active registries of verified families in an active disaster,
    in the mandate's states and categories, not ones this mandate already gave to."""
    already = select(MandateGift.registry_item_id).where(MandateGift.mandate_id == mandate.id)
    query = (
        select(RegistryItem, Registry, Household, DisasterEvent)
        .join(Registry, RegistryItem.registry_id == Registry.id)
        .join(Household, Registry.household_id == Household.id)
        .join(DisasterEvent, Household.disaster_event_id == DisasterEvent.id)
        .where(
            Registry.status == "active",
            RegistryItem.status == "open",
            Household.verification_level >= VERIFIED,
            DisasterEvent.status == "active",
            RegistryItem.id.not_in(already),
            RegistryItem.category.not_in(BLOCKED_CATEGORIES),
        )
        .order_by(RegistryItem.priority, RegistryItem.id)
    )
    if mandate.states:
        query = query.where(Household.state.in_(mandate.states))
    if mandate.categories:
        query = query.where(RegistryItem.category.in_(mandate.categories))
    needs = []
    for item, _reg, home, event in db.execute(query):
        if item.remaining <= 0:
            continue
        needs.append(
            giving.Need(
                item_id=item.id,
                item=item.name,
                note=item.note,
                category=item.category,
                remaining=item.remaining,
                family=home.name,
                place=f"{home.city}, {home.state}",
                disaster=event.name,
            )
        )
        if len(needs) == MAX_NEEDS:
            break
    return needs


def _give(db: Session, mandate: GivingMandate, planned: giving.PlannedGift, by_ai: bool) -> MandateGift | None:
    """Claim, pay, apply. Returns None if this mandate already gave to this need (the claim was refused)."""
    item = db.get(RegistryItem, planned.item_id)
    if item is None:
        return None
    gift = MandateGift(
        mandate_id=mandate.id,
        registry_item_id=item.id,
        amount=planned.amount,
        reason=planned.reason,
        by_ai=by_ai,
        paypal_request_id=f"hearthline-mandate-{mandate.id}-item-{item.id}",  # what the gift is for, never random
    )
    db.add(gift)
    try:
        db.commit()  # the claim: the unique constraints refuse a second gift to the same need
    except IntegrityError:
        db.rollback()
        return None
    donor = mandate.donor
    try:
        donation = registry.new_donation(
            db,
            item.rebuild_registry,
            item_id=item.id,
            amount=gift.amount,
            donor_name=donor.name,
            message=f"Given through {donor.name.split()[0]}'s giving mandate",
            payment_method="paypal",
            donor=donor,
        )
    except registry.DonationError as e:
        gift.status, gift.error = "failed", str(e)[:300]
        db.commit()
        return gift
    gift.donation_id = donation.id
    db.commit()
    return _pay(db, mandate, gift)


def _pay(db: Session, mandate: GivingMandate, gift: MandateGift) -> MandateGift:
    donation = gift.donation
    item = gift.item
    try:
        payment = vault.give(
            mandate.paypal_payment_token_id or "",
            gift.amount,
            f"{registry.CUSTOM_ID_PREFIX}{donation.id}",
            f"Hearthline: {item.name} for the {item.rebuild_registry.household.name}",
            gift.paypal_request_id,
        )
    except vault.VaultError as e:
        gift.status, gift.error = ("checking" if e.outcome_unknown else "failed"), str(e)[:300]
        if not e.outcome_unknown:
            donation.status = "failed"
        db.commit()
        return gift
    donation.paypal_order_id = payment.order_id
    gift.status, gift.error, gift.given_at = "given", None, now()
    _audit(db, mandate, "gave", gift_id=gift.id, item_id=item.id, amount=gift.amount, order_id=payment.order_id)
    db.commit()
    registry.apply_capture(
        db, donation, Capture(payment.order_id, payment.capture_id, "COMPLETED", payment.amount, payment.fee, "paypal")
    )
    return gift


def settle(db: Session, mandate: GivingMandate) -> None:
    """Gifts whose outcome was unknown: resend with the same request id; PayPal answers with the same order."""
    for gift in [g for g in mandate.gifts if g.status == "checking" and g.donation is not None]:
        _pay(db, mandate, gift)


def run(db: Session, mandate: GivingMandate) -> Round:
    """One round of giving within the mandate's limits."""
    if mandate.status != "active" or not mandate.paypal_payment_token_id:
        raise MandateError("This mandate isn't active", 409)
    settle(db, mandate)
    budget = left_this_month(db, mandate)
    needs = eligible(db, mandate) if budget >= MIN_GIFT else []
    mandate.last_run_at = now()
    db.commit()
    if not needs:
        why = "You've reached this month's limit." if budget < MIN_GIFT else "No verified needs match right now."
        return Round([], why, False)
    try:
        plan, summary = giving.choose(mandate.note, needs, budget, mandate.per_gift_max)
        by_ai = True
    except ai.AIError:
        plan, by_ai = giving.fallback(needs, budget, mandate.per_gift_max), False
        summary = f"Gave to {len(plan)} needs, finishing the ones closest to done first."
    gifts = [g for p in plan if (g := _give(db, mandate, p, by_ai)) is not None]
    return Round(gifts, summary, by_ai)


def run_all(db: Session) -> int:
    """Every active mandate gets a round (a new disaster, a newly verified family). Returns how many gifts went out."""
    given = 0
    for mandate in db.scalars(select(GivingMandate).where(GivingMandate.status == "active")):
        try:
            given += sum(1 for g in run(db, mandate).gifts if g.status == "given")
        except Exception:  # one donor's failure never stops the others
            db.rollback()
            log.exception("Giving mandate %s failed", mandate.id)
    return given
