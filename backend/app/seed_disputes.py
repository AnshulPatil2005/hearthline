"""Three PayPal disputes for the demo desk, each with a different right answer. No PayPal calls (DEMO ids).

- Jordan gave $75 to the copycat "Riveras' Rebuild Fund" and now asks if it was real: the rules say refund.
- Gus paid $200 for a Moreno's Bakery card and the bakery is still closed: an inquiry, so explain the escrow.
- A Ridge Outfitters buyer wants the rest of their money back: the refund was already made, so send proof.
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.disputes import DEMO_PREFIX
from app.models import Business, Donation, GiftCard, PaymentDispute, now

ACTIONS = ["send_message", "provide_evidence", "accept_claim"]


def _card(db: Session, slug: str, **where) -> GiftCard | None:
    business = db.scalar(select(Business).where(Business.slug == slug))
    if business is None:
        return None
    for campaign in business.campaigns:
        for card in campaign.cards:
            if all(getattr(card, k) == v for k, v in where.items()):
                return card
    return None


def seed_disputes_demo(db: Session) -> None:
    if db.scalar(select(PaymentDispute.id).where(PaymentDispute.paypal_dispute_id.startswith(DEMO_PREFIX)).limit(1)):
        return
    found: list[PaymentDispute] = []

    scam_gift = db.scalar(select(Donation).where(Donation.paypal_capture_id == "DEMO-SCAM-1"))
    if scam_gift is not None:
        found.append(
            PaymentDispute(
                paypal_dispute_id=f"{DEMO_PREFIX}1001",
                reason="MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED",
                status="WAITING_FOR_SELLER_RESPONSE",
                stage="CHARGEBACK",
                amount=scam_gift.amount,
                transaction_id=scam_gift.paypal_capture_id,
                payer_message="I gave to what I thought was the Rivera family's fund after the Sablewood fire. "
                "A neighbor says a fake page was copying them. Did my money go to the real family?",
                respond_by=now() + timedelta(days=8),
                donation_id=scam_gift.id,
                created_at=now() - timedelta(days=2),
            )
        )

    bakery_card = _card(db, "morenos-bakery", buyer_name="Gus", amount_paid=Decimal("200.00"), status="active")
    if bakery_card is not None:
        found.append(
            PaymentDispute(
                paypal_dispute_id=f"{DEMO_PREFIX}1002",
                reason="MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
                status="WAITING_FOR_SELLER_RESPONSE",
                stage="INQUIRY",
                amount=bakery_card.amount_paid,
                transaction_id=bakery_card.paypal_capture_id,
                payer_message="I paid $200 for a Moreno's Bakery gift card weeks ago and the bakery is still "
                "closed. What happens to my money if they never open?",
                respond_by=now() + timedelta(days=17),
                gift_card_id=bakery_card.id,
                created_at=now() - timedelta(days=1),
            )
        )

    ridge_card = _card(db, "ridge-outfitters", buyer_name="Amir", status="refunded")
    if ridge_card is not None:
        found.append(
            PaymentDispute(
                paypal_dispute_id=f"{DEMO_PREFIX}1003",
                reason="CREDIT_NOT_PROCESSED",
                status="WAITING_FOR_SELLER_RESPONSE",
                stage="CHARGEBACK",
                amount=ridge_card.amount_paid - ridge_card.refunded_amount,
                transaction_id=ridge_card.paypal_capture_id,
                payer_message=f"Ridge Outfitters never reopened. I paid ${ridge_card.amount_paid:.0f} for a gift "
                f"card and only got ${ridge_card.refunded_amount:.2f} back. I want the rest.",
                respond_by=now() + timedelta(days=5),
                gift_card_id=ridge_card.id,
                created_at=now() - timedelta(days=3),
            )
        )

    for d in found:
        d.actions = list(ACTIONS) if d.stage == "INQUIRY" else ["provide_evidence", "accept_claim"]
        db.add(d)
        db.flush()
        audit.record(
            db,
            action="dispute.opened",
            subject_type="payment_dispute",
            subject_id=d.id,
            data={"paypal_dispute_id": d.paypal_dispute_id, "reason": d.reason, "amount": d.amount},
        )
    db.commit()
