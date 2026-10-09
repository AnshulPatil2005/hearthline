"""Payment disputes desk: a payer disputes a donation or a gift card with PayPal.

PayPal tells us through webhooks (and a sync). Code links the dispute to the payment and gathers what Hearthline's
records show (was the item bought and shipped? was the card refunded or used?). Rules in code recommend an answer;
the Funds agent drafts the words. A staff member edits and decides: message the payer, send evidence, or refund.
Nothing goes to PayPal until they do.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ai, audit, ledger, registry, reopen
from app.models import (
    Case,
    Donation,
    GiftCard,
    GiftCardPayment,
    LedgerTransaction,
    PaymentDispute,
    Purchase,
    ReopenRegular,
    User,
    now,
)
from app.paypal import disputes as paypal_disputes
from app.paypal.rest import PayPalError
from app.paypal.webhooks import on

log = logging.getLogger(__name__)

DEMO_PREFIX = "PP-D-DEMO-"
SITE_TZ = ZoneInfo("America/Los_Angeles")
REASONS = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "Says it was never received",
    "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "Says it was not as described",
    "UNAUTHORISED": "Says they did not make this payment",
    "CREDIT_NOT_PROCESSED": "Says a refund was never made",
    "DUPLICATE_TRANSACTION": "Says they were charged twice",
    "INCORRECT_AMOUNT": "Says the amount was wrong",
    "PAYMENT_BY_OTHER_MEANS": "Says they paid another way",
    "CANCELED_RECURRING_BILLING": "Says they had cancelled the monthly payment",
    "PROBLEM_WITH_REMITTANCE": "A problem with the payment",
    "OTHER": "Other",
}
OPEN_CASE = ("in_review", "needs_info", "escalated")
LOST = {"RESOLVED_BUYER_FAVOUR", "ACCEPTED"}  # the money went back to the payer
# How a staff decision maps to PayPal's action, the status it leaves, and what we record.
RESPONSES = {
    "message": ("send_message", "WAITING_FOR_BUYER_RESPONSE", "message_sent"),
    "evidence": ("provide_evidence", "UNDER_REVIEW", "evidence_sent"),
    "refund": ("accept_claim", "RESOLVED", "refunded"),
}
CARRIERS = {"UPS", "USPS", "FEDEX", "DHL", "ONTRAC", "LASERSHIP"}
METHODS = {"paypal": "PayPal", "venmo": "Venmo", "paylater": "PayPal Pay Later"}


class DisputeError(ValueError):
    pass


def is_demo(d: PaymentDispute) -> bool:
    return d.paypal_dispute_id.startswith(DEMO_PREFIX)


# --- Intake -----------------------------------------------------------------------------------------


def _link(db: Session, d: PaymentDispute, custom_id: str | None) -> None:
    """Which donation, gift card or monthly payment the payer is disputing."""
    custom = custom_id or ""
    if custom.startswith(registry.CUSTOM_ID_PREFIX):
        d.donation_id = db.scalar(select(Donation.id).where(Donation.id == int(custom.split(":", 1)[1])))
    elif custom.startswith(reopen.CUSTOM_ID_PREFIX):
        d.gift_card_id = db.scalar(select(GiftCard.id).where(GiftCard.id == int(custom.split(":", 1)[1])))
    if d.donation_id or d.gift_card_id or not d.transaction_id:
        return
    txn = d.transaction_id
    d.donation_id = db.scalar(select(Donation.id).where(Donation.paypal_capture_id == txn))
    d.gift_card_id = db.scalar(select(GiftCard.id).where(GiftCard.paypal_capture_id == txn))
    payment = db.scalar(select(GiftCardPayment).where(GiftCardPayment.paypal_sale_id == txn))
    if payment is not None:
        d.gift_card_payment_id, d.gift_card_id = payment.id, payment.gift_card_id


def upsert(db: Session, info: paypal_disputes.DisputeInfo) -> PaymentDispute:
    """Store a dispute PayPal told us about (new or changed). Safe to call again with the same data."""
    d = db.scalar(select(PaymentDispute).where(PaymentDispute.paypal_dispute_id == info.id))
    new = d is None
    if d is None:
        d = PaymentDispute(paypal_dispute_id=info.id, amount=info.amount)
        db.add(d)
    d.reason, d.status, d.stage = info.reason, info.status, info.stage
    d.amount = info.amount or d.amount
    d.transaction_id = info.transaction_id or d.transaction_id
    d.respond_by, d.outcome, d.actions = info.respond_by or d.respond_by, info.outcome, info.actions
    if info.payer_message:
        d.payer_message = info.payer_message
    if new:
        _link(db, d, info.custom_id)
        db.flush()
        audit.record(
            db,
            action="dispute.opened",
            subject_type="payment_dispute",
            subject_id=d.id,
            data={"paypal_dispute_id": info.id, "reason": info.reason, "amount": info.amount},
        )
    if d.status == "RESOLVED" and d.outcome in LOST:
        _record_loss(db, d)
    db.commit()
    return d


def _on_dispute(db: Session, resource: dict) -> None:
    upsert(db, paypal_disputes.parse(resource))


for _event in ("CUSTOMER.DISPUTE.CREATED", "CUSTOMER.DISPUTE.UPDATED", "CUSTOMER.DISPUTE.RESOLVED"):
    on(_event)(_on_dispute)


def sync(db: Session) -> int:
    """Pull recent disputes from PayPal (a backup for missed webhooks). Returns how many it saw."""
    try:
        found = paypal_disputes.recent()
    except PayPalError as e:
        raise DisputeError(f"PayPal could not list disputes ({e.status})") from e
    for info in found:
        upsert(db, info)
    return len(found)


# --- What our records show ------------------------------------------------------------------------


@dataclass
class Records:
    """Hearthline's side of the story, the evidence PayPal accepts for it, and what the rules recommend."""

    subject: str
    facts: list[tuple[str, str]] = field(default_factory=list)
    timeline: list[tuple[datetime, str]] = field(default_factory=list)
    evidence_type: str = "OTHER"
    tracking: list[dict] = field(default_factory=list)
    recommendation: str = "evidence"  # message | evidence | refund
    because: str = ""


def money(v: Decimal) -> str:
    return f"${v:,.2f}"


def day(dt: datetime | None) -> str:
    """A date as the people in the (California) disaster area see it; stored times are UTC."""
    if dt is None:
        return "unknown"
    local = (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).astimezone(SITE_TZ)
    return f"{local:%b} {local.day}, {local.year}"


def _donation_records(db: Session, d: PaymentDispute, gift: Donation) -> Records:
    reg = gift.rebuild_registry
    item = gift.item
    rec = Records(subject=f'Gift to the registry "{reg.title}"' + (f" for {item.name}" if item else ""))
    method = METHODS.get(gift.payment_method, gift.payment_method)
    rec.facts += [
        ("Paid", f"{money(gift.amount)} by {method} on {day(gift.captured_at)}"),
        ("Registry", f"{reg.title} ({reg.status})"),
    ]
    if gift.captured_at:
        rec.timeline.append((gift.captured_at, f"Gift of {money(gift.amount)} captured"))
    purchase = None
    if item is not None:
        rec.facts.append(("Item", f"{item.name}: {money(item.funded_amount)} of {money(item.target_amount)} funded"))
        purchase = db.scalar(
            select(Purchase)
            .where(Purchase.registry_item_id == item.id, Purchase.status.in_(("paid", "shipped", "delivered")))
            .order_by(Purchase.id.desc())
        )
    if purchase is not None:
        rec.facts.append(("Bought", f"{purchase.title} from {purchase.retailer} for {money(purchase.total)}"))
        if purchase.paid_at:
            rec.timeline.append((purchase.paid_at, f"Shopper bought {purchase.title} from {purchase.retailer}"))
        if purchase.tracking_number:
            shipment = f"{purchase.carrier or 'Carrier'} {purchase.tracking_number}: {purchase.status}"
            rec.facts.append(("Shipment", shipment))
    flagged = db.scalar(
        select(Case).where(Case.household_id == reg.household_id, Case.status.in_(OPEN_CASE), Case.risk_tier == "high")
    )
    held = ledger.household_available(db, reg.household_id)
    if gift.status == "refunded":
        rec.evidence_type, rec.recommendation = "PROOF_OF_REFUND", "evidence"
        rec.because = "This gift was already refunded to the payer."
    elif flagged is not None:
        rec.facts.append(("Review", f"Open high-risk case: {flagged.title}"))
        rec.recommendation = "refund"
        rec.because = (
            "Reviewers are checking this registry as a possible scam, so Hearthline should not keep the gift."
            + (" The money hasn't been spent." if held >= d.amount else " Part of it was already spent.")
        )
    elif d.reason == "UNAUTHORISED":
        rec.recommendation = "refund"
        rec.because = "The payer says they didn't make this gift; Hearthline refunds gifts that weren't authorized."
    elif purchase is not None and purchase.tracking_number:
        rec.evidence_type, rec.recommendation = "PROOF_OF_FULFILLMENT", "evidence"
        carrier = (purchase.carrier or "OTHER").upper()
        rec.tracking = [
            {"carrier_name": carrier if carrier in CARRIERS else "OTHER", "tracking_number": purchase.tracking_number}
        ]
        rec.because = (
            f"The Shopper bought {purchase.title} with this gift and {purchase.carrier} shows it {purchase.status}."
        )
    else:
        rec.recommendation = "message" if d.stage == "INQUIRY" else "evidence"
        rec.because = "The gift is held for the family and hasn't been spent yet; explain where it is going."
    return rec


def _card_records(db: Session, d: PaymentDispute, card: GiftCard) -> Records:
    campaign = card.campaign
    business = campaign.business
    rec = Records(subject=f"Gift card from {business.name} (Reopen Fund)")
    payment = d.gift_card_payment
    paid = f"{money(card.amount_paid)} for a card worth {money(card.face_value)} ({campaign.bonus_percent}% bonus)"
    rec.facts += [
        ("Card", f"Ending {card.code[-4:]}, {card.status}, balance {money(card.balance)}"),
        ("Paid", paid if payment is None else f"Monthly payment of {money(payment.amount)} as a regular"),
        (
            "Terms",
            f"Held in escrow and paid to {business.name} only in staff-approved steps; what's left is refunded "
            f"if it doesn't reopen by {day(campaign.reopen_by)}",
        ),
    ]
    if card.activated_at:
        rec.timeline.append((card.activated_at, f"Card bought for {money(card.amount_paid)}"))
    released = sum((t.amount for t in campaign.tranches if t.status == "released"), Decimal(0))
    for t in campaign.tranches:
        if t.status == "released" and t.released_at:
            rec.timeline.append((t.released_at, f"Staff released {money(t.amount)} to {business.name}: {t.title}"))
    if released:
        rec.facts.append(("Released", f"{money(released)} paid to {business.name} in staff-approved rebuilding steps"))
    for r in card.redemptions:
        rec.timeline.append((r.created_at, f"Redeemed {money(r.amount)} at {business.name}"))
    if campaign.refunded_at:
        rec.timeline.append((campaign.refunded_at, f"{business.name} missed its date; escrow refunded to buyers"))
    used = sum((r.amount for r in card.redemptions), Decimal(0))
    if card.refunded_amount > 0:
        rec.facts.append(("Refunded", f"{money(card.refunded_amount)} on {day(campaign.refunded_at)}"))
        rec.evidence_type, rec.recommendation = "PROOF_OF_REFUND", "evidence"
        rec.because = f"Hearthline already refunded {money(card.refunded_amount)}, all that was left in escrow for it"
        if released:
            rec.because += f"; {money(released)} had gone to the business for rebuilding first, as the terms say."
        else:
            rec.because += "."
    elif used > 0:
        rec.facts.append(("Used", f"{money(used)} spent at {business.name}"))
        rec.evidence_type, rec.recommendation = "PROOF_OF_FULFILLMENT", "evidence"
        rec.because = f"The card was used at {business.name} ({money(used)} so far)."
    elif d.reason in {"UNAUTHORISED", "DUPLICATE_TRANSACTION"}:
        rec.recommendation = "refund"
        rec.because = "The card hasn't been used and the payer says this payment wasn't theirs or was a double."
    elif campaign.status == "reopened":
        rec.facts.append(("Reopened", day(campaign.reopened_at)))
        rec.recommendation = "message" if d.stage == "INQUIRY" else "evidence"
        rec.because = f"{business.name} has reopened and the card is ready to use."
    else:
        # If the business misses its date, buyers share what's left in escrow in proportion to what they paid.
        held = max(reopen.escrow_balance(db, campaign.id), Decimal(0))
        active = [c for c in campaign.cards if c.status == "active" and c.amount_paid > 0]
        paid_in = sum((c.amount_paid for c in active), Decimal(0))
        share = (
            min(card.amount_paid, (held * card.amount_paid / paid_in).quantize(reopen.CENT))
            if paid_in
            else card.amount_paid
        )
        rec.facts.append(
            ("Escrow", f"{money(held)} still held for {len(active)} cards; this card's share is {money(share)}")
        )
        rec.recommendation = "message" if d.stage == "INQUIRY" else "evidence"
        rec.because = f"{business.name} is still closed. If it doesn't reopen by {day(campaign.reopen_by)}, "
        if share < card.amount_paid:
            rec.because += (
                f"this card's share of what's left in escrow ({money(share)} of {money(card.amount_paid)}) comes back "
                f"automatically; {money(released)} has already gone to rebuilding, as the card's terms say."
            )
        else:
            rec.because += f"the full {money(card.amount_paid)} comes back automatically."
    return rec


def records(db: Session, d: PaymentDispute) -> Records:
    if d.donation is not None:
        rec = _donation_records(db, d, d.donation)
    elif d.gift_card is not None:
        rec = _card_records(db, d, d.gift_card)
    else:
        rec = Records(subject="A payment Hearthline could not match", recommendation="evidence")
        rec.because = "No donation or gift card matches this transaction; check it by hand before answering."
    rec.timeline.sort(key=lambda x: x[0])
    allowed = {RESPONSES[k][0]: k for k in RESPONSES}
    if not is_demo(d) and RESPONSES[rec.recommendation][0] not in d.actions:  # PayPal won't take that now
        rec.recommendation = next((allowed[a] for a in d.actions if a in allowed), rec.recommendation)
    return rec


# --- The Funds agent's draft ---------------------------------------------------------------------------


class Draft(BaseModel):
    note: str = Field(description="Hearthline's response, 3-6 sentences, plain English")


DRAFT_SYSTEM = """You write Hearthline's response in a PayPal dispute. Hearthline is a nonprofit platform for
disaster recovery: donors give to a family's registry of specific items, and people buy gift cards from local
businesses that are closed after the disaster (the money is held in escrow and refunded if the business misses its
reopening date). The reader is the payer and PayPal's reviewer.

Rules:
- Use only the facts given. Never invent dates, amounts, names, tracking numbers or outcomes.
- 3-6 sentences, plain and respectful, no blame, no exclamation marks.
- Say what Hearthline's records show, with dates and amounts, then what Hearthline is doing (the recommended action):
  "message" = explain and invite the payer to reply; "evidence" = ask PayPal to close the dispute in Hearthline's
  favor; "refund" = say Hearthline is refunding the full disputed amount and why.
- Never promise a refund, or a larger one, than the facts and "why" state. If only a share comes back, say so.
- Never include a family's address, phone or other private details. Write in English."""


def _template(d: PaymentDispute, rec: Records) -> str:
    shown = "; ".join(f"{label.lower()}: {value}" for label, value in rec.facts)
    closing = {
        "refund": f"Hearthline is refunding the full {money(d.amount)}.",
        "message": "Please reply here with any questions; we're glad to help.",
        "evidence": "We ask PayPal to close this dispute.",
    }[rec.recommendation]
    return f"Thank you for raising this. {rec.because} Hearthline's records for {rec.subject}: {shown}. {closing}"


def draft(db: Session, d: PaymentDispute, force: bool = False) -> PaymentDispute:
    """Fill in the draft response (the Funds agent, or a template when AI is unavailable)."""
    if d.draft and not force:
        return d
    rec = records(db, d)
    d.draft, d.draft_by_ai = _template(d, rec), False
    if ai.configured():
        facts = {
            "dispute": {
                "reason": REASONS.get(d.reason, d.reason),
                "stage": d.stage,
                "amount": str(d.amount),
                "payer_says": d.payer_message,
            },
            "subject": rec.subject,
            "records": dict(rec.facts),
            "timeline": [f"{day(at)}: {what}" for at, what in rec.timeline],
            "recommended_action": rec.recommendation,
            "why": rec.because,
        }
        try:
            result = ai.parse(Draft, system=DRAFT_SYSTEM, content=[ai.text_part(json.dumps(facts))], max_tokens=600)
            if len(result.note.strip()) >= 40:
                d.draft, d.draft_by_ai = result.note.strip()[:2000], True
        except ai.AIError:
            log.warning("Dispute draft fell back to the template")
    d.recommendation = rec.recommendation
    db.commit()
    return d


# --- Staff decisions ----------------------------------------------------------------------------------


def _record_loss(db: Session, d: PaymentDispute) -> None:
    """The payer got the money back: take it from what we hold for them, and book the rest as a loss. Once."""
    ref = f"dispute-{d.paypal_dispute_id}"
    if db.scalar(select(LedgerTransaction.id).where(LedgerTransaction.paypal_ref == ref)):
        return
    amount = d.amount
    lines: dict[str, Decimal] = {ledger.CASH: -amount}
    household_id = None
    if d.donation is not None:
        gift = d.donation
        household_id = gift.rebuild_registry.household_id
        held = min(amount, max(ledger.household_available(db, household_id), Decimal(0)))
        lines[ledger.household_fund(household_id)] = held
        lines[ledger.DISPUTE_LOSSES] = amount - held
        if amount >= gift.amount:
            gift.status = "refunded"
        if gift.item is not None and gift.item.status in ("open", "funded"):
            gift.item.funded_amount = max(Decimal(0), gift.item.funded_amount - amount)
            if gift.item.funded_amount < gift.item.target_amount:
                gift.item.status = "open"
    elif d.gift_card is not None:
        card = d.gift_card
        held = min(amount, max(reopen.escrow_balance(db, card.campaign_id), Decimal(0)))
        lines[reopen.escrow_account(card.campaign_id)] = held
        lines[ledger.DISPUTE_LOSSES] = amount - held
        value = (amount * card.face_value / card.amount_paid).quantize(reopen.CENT) if card.amount_paid else amount
        card.refunded_amount += amount
        card.balance = max(Decimal(0), card.balance - value)
        if card.refunded_amount >= card.amount_paid:
            card.status, card.balance = "refunded", Decimal(0)
        if d.gift_card_payment is not None:
            d.gift_card_payment.refunded_amount += amount
            regular = db.scalar(select(ReopenRegular).where(ReopenRegular.gift_card_id == card.id))
            if regular is not None and d.reason == "CANCELED_RECURRING_BILLING":
                regular.status = "cancelled"
    else:
        lines[ledger.DISPUTE_LOSSES] = amount
    ledger.post(
        db,
        kind="refund",
        description=f"Dispute {d.paypal_dispute_id}: refunded to the payer",
        household_id=household_id,
        paypal_ref=ref,
        meta={"dispute_id": d.id, "donation_id": d.donation_id, "gift_card_id": d.gift_card_id},
        lines=lines,
    )


def _paypal_message(e: PayPalError) -> str:
    body = e.body if isinstance(e.body, dict) else {}
    details = body.get("details") or [{}]
    return details[0].get("description") or body.get("message") or f"error {e.status}"


def respond(db: Session, d: PaymentDispute, action: str, note: str, actor: User) -> PaymentDispute:
    """A staff member's decision. Only now does anything go to PayPal."""
    if action not in RESPONSES:
        raise DisputeError("Choose message, evidence or refund")
    if d.status == "RESOLVED" or d.decision in {"evidence_sent", "refunded"}:
        raise DisputeError("This dispute has already been answered")
    note = note.strip()
    if len(note) < 20:
        raise DisputeError("Write a response of at least a sentence")
    paypal_action, status, decision = RESPONSES[action]
    if not is_demo(d) and paypal_action not in d.actions:
        raise DisputeError("PayPal doesn't allow that at this stage of the dispute")
    rec = records(db, d)
    if not is_demo(d):
        try:
            if action == "message":
                paypal_disputes.send_message(d.paypal_dispute_id, note)
            elif action == "evidence":
                from app.dispute_pdf import build

                paypal_disputes.provide_evidence(
                    d.paypal_dispute_id,
                    rec.evidence_type,
                    note,
                    tracking=rec.tracking,
                    document=(f"hearthline-{d.paypal_dispute_id}.pdf", build(d, rec, note)),
                )
            else:
                paypal_disputes.accept_claim(d.paypal_dispute_id, note, d.amount)
        except PayPalError as e:
            raise DisputeError(f"PayPal refused: {_paypal_message(e)}") from e
    d.draft, d.decision, d.status = note, decision, status
    d.decided_by_user_id, d.decided_at = actor.id, now()
    if action == "refund":
        d.outcome = "ACCEPTED"
        _record_loss(db, d)
    audit.record(
        db,
        actor_user_id=actor.id,
        action=f"dispute.{decision}",
        subject_type="payment_dispute",
        subject_id=d.id,
        data={
            "paypal_dispute_id": d.paypal_dispute_id,
            "recommended": rec.recommendation,
            "evidence_type": rec.evidence_type if action == "evidence" else None,
            "amount": d.amount,
        },
    )
    db.commit()
    return d
