"""Insurers pay contents claims through PayPal.

The household prepares a claim from what Hearthline already knows: the inventory scanned before the disaster (with
photos, prices and when each item was recorded) and the policy the Policy agent read. Code applies the policy's
sub-limits, contents limit and deductible to estimate what is payable. The insurer's adjuster opens the claim with a
private link, decides the amount (a person decides; the estimate only informs), and pays it with PayPal. Hearthline
captures the payment and immediately pays the same amount out to the household's own PayPal account, so the family
gets the money in minutes instead of waiting for a mailed check. Both steps go into the ledger.
"""

import logging
import secrets
from dataclasses import dataclass
from decimal import Decimal

from paypalserversdk.exceptions.error_exception import ErrorException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, claims, ledger
from app.agents.policy_agent import PolicySummary
from app.media import media_url
from app.models import Household, InsuranceClaim, InsurancePolicy, Item, Media, now
from app.paypal import orders, payouts
from app.paypal.orders import Capture
from app.paypal.rest import PayPalError
from app.paypal.webhooks import on

log = logging.getLogger(__name__)
CUSTOM_ID_PREFIX = "claim:"
CENT = Decimal("0.01")


class ClaimError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def estimate(check: claims.ClaimCheck) -> Decimal:
    """What the policy's limits suggest: the inventory, less what sub-limits cut, capped by the contents limit, less
    the deductible. The adjuster decides the real amount."""
    after_sub_limits = check.inventory_value - sum((s.over_by for s in check.sub_limits), Decimal(0))
    capped = min(after_sub_limits, check.contents_limit) if check.contents_limit is not None else after_sub_limits
    return max(capped - (check.deductible or Decimal(0)), Decimal(0)).quantize(CENT)


def latest_policy(db: Session, household_id: int) -> InsurancePolicy | None:
    return db.scalar(
        select(InsurancePolicy)
        .where(InsurancePolicy.household_id == household_id, InsurancePolicy.summary.is_not(None))
        .order_by(InsurancePolicy.id.desc())
    )


def current(db: Session, household_id: int) -> InsuranceClaim | None:
    return db.scalar(
        select(InsuranceClaim).where(InsuranceClaim.household_id == household_id).order_by(InsuranceClaim.id.desc())
    )


def prepare(db: Session, home: Household, actor_user_id: int | None = None) -> InsuranceClaim:
    """Build (or rebuild, if it isn't paid yet) the household's claim from their inventory and policy."""
    policy = latest_policy(db, home.id)
    if policy is None:
        raise ClaimError("Upload your policy first, so the claim can follow its limits")
    items = list(db.scalars(select(Item).where(Item.household_id == home.id).order_by(Item.room_id, Item.id)))
    if not items:
        raise ClaimError("Your inventory is empty: scan your rooms first")
    summary = PolicySummary.model_validate(policy.summary)
    check = claims.check(summary, home, items)
    under = {name: s.what for s in check.sub_limits for name in s.items}
    taken = {
        m.id: m.captured_at
        for m in db.scalars(select(Media).where(Media.id.in_([i.media_id for i in items if i.media_id])))
    }
    snapshot = []
    for item in items:
        recorded = taken.get(item.media_id) or item.created_at
        snapshot.append(
            {
                "name": item.name,
                "room": item.room.name if item.room else None,
                "category": item.category,
                "quantity": item.quantity,
                "value": str(item.total_value or Decimal(0)),
                "evidence": str(item.evidence_level),
                "recorded_at": recorded.isoformat() if recorded else None,
                "media_id": item.media_id,
                "price_source": item.price_source,
                "retailer": item.retailer,
                "sub_limit": under.get(item.name),
            }
        )
    claim = current(db, home.id)
    if claim is not None and claim.status == "paid":
        raise ClaimError("This claim has been paid")
    if claim is None:
        claim = InsuranceClaim(household_id=home.id, token=secrets.token_urlsafe(18), insurer=summary.insurer)
        db.add(claim)
    claim.policy_id, claim.insurer, claim.policy_number = policy.id, summary.insurer, summary.policy_number
    claim.loss_date, claim.items = check.loss_date, snapshot
    claim.sub_limits = [s.model_dump(mode="json") for s in check.sub_limits if s.items]
    claim.inventory_value, claim.contents_limit, claim.deductible = (
        check.inventory_value,
        check.contents_limit,
        check.deductible,
    )
    claim.estimate = estimate(check)
    db.flush()
    audit.record(
        db,
        actor_user_id=actor_user_id,
        action="claim.prepared",
        subject_type="insurance_claim",
        subject_id=claim.id,
        data={"items": len(snapshot), "inventory_value": claim.inventory_value, "estimate": claim.estimate},
    )
    db.commit()
    return claim


def by_token(db: Session, token: str) -> InsuranceClaim:
    claim = db.scalar(select(InsuranceClaim).where(InsuranceClaim.token == token))
    if claim is None:
        raise ClaimError("Claim not found", 404)
    return claim


@dataclass
class PacketItem:
    name: str
    room: str | None
    category: str
    quantity: int
    value: Decimal
    evidence: str
    recorded_at: str | None
    photo_url: str | None
    price_source: str | None
    retailer: str | None
    sub_limit: str | None


def packet_items(claim: InsuranceClaim) -> list[PacketItem]:
    """The claimed items with signed photo links, for the adjuster."""
    return [
        PacketItem(
            name=i["name"],
            room=i.get("room"),
            category=i.get("category", "other"),
            quantity=i.get("quantity", 1),
            value=Decimal(i["value"]),
            evidence=i.get("evidence", "photo"),
            recorded_at=i.get("recorded_at"),
            photo_url=media_url(i["media_id"]) if i.get("media_id") else None,
            price_source=i.get("price_source"),
            retailer=i.get("retailer"),
            sub_limit=i.get("sub_limit"),
        )
        for i in claim.items
    ]


def start_payment(db: Session, claim: InsuranceClaim, amount: Decimal, adjuster: str, note: str) -> str:
    """The adjuster approved `amount`: a PayPal order they pay with their insurer's PayPal account."""
    if claim.status == "paid":
        raise ClaimError("This claim has already been paid")
    amount = amount.quantize(CENT)
    if amount <= 0 or amount > claim.inventory_value:
        raise ClaimError(f"The amount must be between $0.01 and the claimed ${claim.inventory_value:,.2f}", 400)
    if not adjuster.strip():
        raise ClaimError("Enter the adjuster's name", 400)
    try:
        order_id = orders.create_order(
            amount=amount,
            description=f"{claim.insurer} contents claim {claim.policy_number or ''}".strip()[:127],
            custom_id=f"{CUSTOM_ID_PREFIX}{claim.id}",
            reference_id=f"claim-{claim.id}",
        )
    except ErrorException as e:
        raise ClaimError("PayPal couldn't start the payment. Try again in a moment.", 502) from e
    claim.adjuster_name, claim.adjuster_note = adjuster.strip()[:120], note.strip()[:500] or None
    claim.approved_amount, claim.paypal_order_id = amount, order_id
    audit.record(
        db,
        action="claim.approved_by_adjuster",
        subject_type="insurance_claim",
        subject_id=claim.id,
        data={"adjuster": claim.adjuster_name, "amount": amount, "estimate": claim.estimate, "order_id": order_id},
    )
    db.commit()
    return order_id


def complete(db: Session, claim: InsuranceClaim, capture: Capture) -> InsuranceClaim:
    """The insurer paid: book it for the household, then send it on to their own PayPal account. Safe twice."""
    if claim.status == "paid" or capture.status != "COMPLETED":
        return claim
    home = claim.household
    claim.status, claim.paid_at, claim.paypal_capture_id = "paid", now(), capture.capture_id
    ledger.post(
        db,
        kind="insurance_payment",
        description=f"Contents claim paid by {claim.insurer}",
        household_id=home.id,
        paypal_ref=capture.capture_id,
        meta={"claim_id": claim.id, "adjuster": claim.adjuster_name},
        lines={
            ledger.CASH: capture.amount - capture.fee,
            ledger.FEES: capture.fee,
            ledger.household_fund(home.id): -capture.amount,
        },
    )
    audit.record(
        db,
        action="claim.paid",
        subject_type="insurance_claim",
        subject_id=claim.id,
        data={"amount": capture.amount, "capture_id": capture.capture_id, "adjuster": claim.adjuster_name},
    )
    db.commit()
    _pay_household(db, claim, capture.amount)
    return claim


def _pay_household(db: Session, claim: InsuranceClaim, amount: Decimal) -> None:
    home = claim.household
    if not home.payout_email:
        claim.payout_status = "held"  # kept in the household's fund until they connect a PayPal account
        db.commit()
        return
    try:
        result = payouts.send_payouts(
            [(home.payout_email, amount, f"Insurance claim payment from {claim.insurer}"[:200], f"claim-{claim.id}")],
            batch_id=payouts.batch_id_for("claim", claim.id, claim.created_at),
            subject=f"Your {claim.insurer} claim payment",
        )
    except PayPalError as e:
        log.warning("Claim %s payout failed: %s", claim.id, payouts.failure_reason(e))
        claim.payout_status = "held"
        db.commit()
        return
    claim.payout_status, claim.payout_ref = "sent", result.batch_id
    ledger.record_spend(
        db,
        kind="claim_payout",
        household_id=home.id,
        amount=amount,
        paypal_ref=result.batch_id,
        description=f"{claim.insurer} claim payment sent to your PayPal account",
        meta={"claim_id": claim.id},
    )
    audit.record(
        db,
        action="claim.paid_out",
        subject_type="insurance_claim",
        subject_id=claim.id,
        data={"amount": amount, "batch_id": result.batch_id},
    )
    db.commit()


@on("PAYMENT.CAPTURE.COMPLETED")
def on_capture_completed(db: Session, resource: dict) -> None:
    """Backup path: the adjuster closed the tab before our capture call returned."""
    custom_id = resource.get("custom_id") or ""
    if not custom_id.startswith(CUSTOM_ID_PREFIX):
        return
    claim = db.get(InsuranceClaim, int(custom_id.removeprefix(CUSTOM_ID_PREFIX)))
    if claim is None:
        return
    capture = Capture(
        order_id=claim.paypal_order_id or "",
        capture_id=resource["id"],
        status=resource["status"],
        amount=Decimal(resource["amount"]["value"]),
        fee=Decimal(resource.get("seller_receivable_breakdown", {}).get("paypal_fee", {}).get("value", "0")),
        payment_method="paypal",
    )
    complete(db, claim, capture)
