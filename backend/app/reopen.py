"""Reopen Fund: local businesses pre-sell gift cards to pay for reopening.

- Only a business that staff have verified (license checked, shop inside the disaster area) can sell cards.
- Card money waits in the campaign's escrow account. The business asks for it in tranches ("replace the
  ovens"); a staff member who isn't the owner approves each one, and PayPal Payouts sends it.
- Cards can be spent once the business reopens. Buyers often get a bonus (a $50 card worth $60).
- If the business hasn't reopened by its date, whatever is still in escrow goes back to buyers,
  in proportion to what each paid, through PayPal refunds.
"""

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from decimal import ROUND_DOWN, Decimal

from paypalserversdk.exceptions.error_exception import ErrorException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, ledger
from app.config import get_settings
from app.models import (
    Business,
    GiftCard,
    GiftCardPayment,
    GiftCardRedemption,
    ReopenCampaign,
    ReopenRegular,
    ReopenTranche,
    User,
    now,
)
from app.paypal import orders, payouts, subscriptions
from app.paypal.orders import Capture
from app.paypal.rest import PayPalError
from app.paypal.webhooks import on

CUSTOM_ID_PREFIX = "giftcard:"
REGULAR_PREFIX = "regular:"
MAX_BONUS_PERCENT = 25
CARD_MIN, CARD_MAX = Decimal("10"), Decimal("500")
CODE_LETTERS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O or 1/I: codes are read aloud and typed
CENT = Decimal("0.01")


class ReopenError(ValueError):
    pass


def escrow_account(campaign_id: int) -> str:
    return f"liabilities:reopen:campaign:{campaign_id}"


def escrow_balance(db: Session, campaign_id: int) -> Decimal:
    return -ledger.balance(db, escrow_account(campaign_id))


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def new_code(business: Business) -> str:
    prefix = "".join(c for c in business.slug.upper() if c.isalnum())[:6] or "CARD"
    groups = ("".join(secrets.choice(CODE_LETTERS) for _ in range(4)) for _ in range(2))
    return f"{prefix}-{'-'.join(groups)}"


def normalize_code(code: str) -> str:
    return code.strip().upper().replace(" ", "")


def current_campaign(business: Business) -> ReopenCampaign | None:
    return next((c for c in reversed(business.campaigns) if c.status in {"live", "reopened"}), None)


# --- Staff: verify the business ------------------------------------------------------------------


def verify_business(db: Session, business: Business, staff: User, approve: bool, note: str) -> Business:
    if staff.id == business.owner_user_id:
        raise ReopenError("Someone other than the owner has to verify a business")
    business.verification = "verified" if approve else "rejected"
    business.verification_note, business.verified_by_user_id = note, staff.id
    audit.record(
        db,
        actor_user_id=staff.id,
        action="business.verified" if approve else "business.rejected",
        subject_type="business",
        subject_id=business.id,
        data={"note": note},
    )
    db.commit()
    return business


# --- Owner: the campaign ---------------------------------------------------------------------------


def create_campaign(
    db: Session,
    business: Business,
    *,
    bonus_percent: int,
    reopen_by: datetime,
    tranches: list[dict],
    actor: User,
) -> ReopenCampaign:
    if business.verification != "verified":
        raise ReopenError("Your business needs to be verified before it can sell gift cards")
    if current_campaign(business):
        raise ReopenError("You already have a Reopen Fund running")
    if not 0 <= bonus_percent <= MAX_BONUS_PERCENT:
        raise ReopenError(f"The bonus can be 0% to {MAX_BONUS_PERCENT}%")
    reopen_by = _aware(reopen_by)
    if not now() + timedelta(days=7) <= reopen_by <= now() + timedelta(days=365):
        raise ReopenError("Pick a reopening date between a week and a year from now")
    if not tranches:
        raise ReopenError("List what the money will pay for")
    campaign = ReopenCampaign(
        business_id=business.id,
        goal_amount=sum((Decimal(str(t["amount"])) for t in tranches), Decimal(0)),
        bonus_percent=bonus_percent,
        reopen_by=reopen_by,
    )
    for seq, t in enumerate(tranches, start=1):
        start, end = _aware(t["start_date"]), _aware(t["end_date"])
        if end < start:
            raise ReopenError(f"Step {seq} ends before it starts")
        campaign.tranches.append(
            ReopenTranche(seq=seq, title=t["title"], amount=Decimal(str(t["amount"])), start_date=start, end_date=end)
        )
    business.campaigns.append(campaign)
    db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        action="reopen.campaign_created",
        subject_type="reopen_campaign",
        subject_id=campaign.id,
        data={"goal": campaign.goal_amount, "bonus_percent": bonus_percent},
    )
    db.commit()
    return campaign


def mark_reopened(db: Session, campaign: ReopenCampaign, owner: User) -> ReopenCampaign:
    if campaign.status != "live":
        raise ReopenError(f"This campaign is {campaign.status}")
    campaign.status, campaign.reopened_at = "reopened", now()
    audit.record(
        db, actor_user_id=owner.id, action="reopen.reopened", subject_type="reopen_campaign", subject_id=campaign.id
    )
    db.commit()
    return campaign


# --- Buyers: gift cards ------------------------------------------------------------------------------


def start_card(
    db: Session, campaign: ReopenCampaign, amount: Decimal, buyer_name: str | None, buyer: User | None, method: str
) -> GiftCard:
    if campaign.status != "live" or now() >= _aware(campaign.reopen_by):
        raise ReopenError("This Reopen Fund isn't selling cards right now")
    if not CARD_MIN <= amount <= CARD_MAX:
        raise ReopenError(f"Cards are ${CARD_MIN:.0f} to ${CARD_MAX:.0f}")
    left = campaign.goal_amount - campaign.raised
    if amount > left:
        raise ReopenError(f"The goal is almost reached: the most you can buy is ${left:.2f}")
    face = (amount * (100 + campaign.bonus_percent) / 100).quantize(CENT)
    card = GiftCard(
        campaign_id=campaign.id,
        code=new_code(campaign.business),
        buyer_name=(buyer_name or "").strip()[:120] or None,
        buyer_user_id=buyer.id if buyer else None,
        amount_paid=amount,
        face_value=face,
        payment_method=method,
    )
    db.add(card)
    db.flush()
    return card


def buyer_token(kind: str, record_id: int) -> str:
    """Proof that a request comes from whoever bought the card: its code is a bearer secret, and ids are guessable."""
    key = get_settings().secret_key.encode()
    return hmac.new(key, f"{kind}:{record_id}".encode(), hashlib.sha256).hexdigest()[:32]


def is_buyer(kind: str, record_id: int, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(token, buyer_token(kind, record_id))


def activate(db: Session, card: GiftCard, capture: Capture) -> GiftCard:
    """The buyer paid: the card gets its value and the money goes into the campaign's escrow. Safe twice, and
    safe when the buyer's browser and PayPal's webhook get here at the same time."""
    db.flush()
    db.refresh(card, with_for_update=True)  # one at a time; the second sees "active" (no lock on SQLite)
    if card.status == "active" or capture.status != "COMPLETED":
        return card
    campaign = card.campaign
    db.refresh(campaign, with_for_update=True)  # what other cards have added to `raised` meanwhile
    card.status, card.balance, card.activated_at = "active", card.face_value, now()
    card.paypal_capture_id = capture.capture_id
    if capture.payment_method == "venmo":
        card.payment_method = "venmo"
    campaign.raised += card.amount_paid
    ledger.post(
        db,
        kind="gift_card",
        description=f"Gift card for {campaign.business.name}",
        paypal_ref=capture.capture_id,
        meta={"gift_card_id": card.id, "campaign_id": campaign.id},
        lines={
            ledger.CASH: capture.amount - capture.fee,
            ledger.FEES: capture.fee,
            escrow_account(campaign.id): -capture.amount,
        },
    )
    audit.record(
        db,
        actor_user_id=card.buyer_user_id,
        action="gift_card.activated",
        subject_type="gift_card",
        subject_id=card.id,
        data={"paid": card.amount_paid, "face_value": card.face_value, "capture_id": capture.capture_id},
    )
    db.commit()
    return card


@on("PAYMENT.CAPTURE.COMPLETED")
def on_capture_completed(db: Session, resource: dict) -> None:
    """Backup path when the buyer closes the tab before our capture call returns."""
    custom_id = resource.get("custom_id") or ""
    if not custom_id.startswith(CUSTOM_ID_PREFIX):
        return
    card = db.get(GiftCard, int(custom_id.removeprefix(CUSTOM_ID_PREFIX)))
    if card is None:
        return
    activate(
        db,
        card,
        Capture(
            order_id=card.paypal_order_id or "",
            capture_id=resource["id"],
            status=resource["status"],
            amount=Decimal(resource["amount"]["value"]),
            fee=Decimal(resource.get("seller_receivable_breakdown", {}).get("paypal_fee", {}).get("value", "0")),
            payment_method=card.payment_method,
        ),
    )


def redeem(db: Session, business: Business, code: str, amount: Decimal, by: User) -> GiftCard:
    card = db.scalar(select(GiftCard).where(GiftCard.code == normalize_code(code)))
    if card is None or card.status == "pending":
        raise ReopenError("No gift card with that code")
    if card.campaign.business_id != business.id:
        raise ReopenError("This card is for another business")
    if card.campaign.status != "reopened":
        raise ReopenError("Cards can be used once you've marked the business as reopened")
    if card.status != "active":
        raise ReopenError(f"This card was {card.status}")
    if not Decimal(0) < amount <= card.balance:
        raise ReopenError(f"This card has ${card.balance:.2f} left")
    card.balance -= amount
    card.redemptions.append(GiftCardRedemption(amount=amount, redeemed_by_user_id=by.id))
    audit.record(
        db,
        actor_user_id=by.id,
        action="gift_card.redeemed",
        subject_type="gift_card",
        subject_id=card.id,
        data={"amount": amount, "balance": card.balance},
    )
    db.commit()
    return card


# --- Tranches: the business asks, staff approve, Payouts pays --------------------------------------


def request_tranche(db: Session, tranche: ReopenTranche, owner: User, note: str) -> ReopenTranche:
    campaign = tranche.campaign
    if campaign.status not in {"live", "reopened"}:
        raise ReopenError(f"This campaign is {campaign.status}")
    if tranche.status not in {"pending", "rejected"}:
        raise ReopenError(f"This step is {tranche.status}")
    held = escrow_balance(db, campaign.id)
    if held < tranche.amount:
        raise ReopenError(f"Not enough raised yet: ${held:.2f} is waiting in escrow")
    tranche.status, tranche.request_note, tranche.decision_note = "requested", note, None
    audit.record(
        db,
        actor_user_id=owner.id,
        action="reopen.tranche_requested",
        subject_type="reopen_tranche",
        subject_id=tranche.id,
        data={"amount": tranche.amount, "note": note},
    )
    db.commit()
    return tranche


def decide_tranche(db: Session, tranche: ReopenTranche, staff: User, approve: bool, note: str) -> ReopenTranche:
    campaign = tranche.campaign
    business = campaign.business
    if staff.id == business.owner_user_id:
        raise ReopenError("Someone other than the owner has to approve this")
    if tranche.status != "requested":
        raise ReopenError(f"This step is {tranche.status}")
    tranche.decided_by_user_id, tranche.decision_note = staff.id, note
    if not approve:
        tranche.status = "rejected"
        audit.record(
            db,
            actor_user_id=staff.id,
            action="reopen.tranche_rejected",
            subject_type="reopen_tranche",
            subject_id=tranche.id,
            data={"note": note},
        )
        db.commit()
        return tranche
    if escrow_balance(db, campaign.id) < tranche.amount:
        raise ReopenError("Not enough is left in escrow for this step")
    if not business.payout_email:
        raise ReopenError("The business hasn't connected a PayPal account yet")
    try:
        result = payouts.send_payouts(
            [(business.payout_email, tranche.amount, f"Reopen Fund: {tranche.title}", f"tranche-{tranche.id}")],
            batch_id=payouts.batch_id_for("tranche", tranche.id, campaign.created_at),
            subject=f"Your Reopen Fund: {tranche.title}",
        )
    except PayPalError as e:
        raise ReopenError(payouts.failure_reason(e)) from e
    ledger.post(
        db,
        kind="tranche_payout",
        description=f"{business.name}: {tranche.title}",
        paypal_ref=result.batch_id,
        meta={"campaign_id": campaign.id, "tranche_id": tranche.id},
        lines={escrow_account(campaign.id): tranche.amount, ledger.CASH: -tranche.amount},
    )
    tranche.status, tranche.paypal_ref, tranche.released_at = "released", result.batch_id, now()
    audit.record(
        db,
        actor_user_id=staff.id,
        action="reopen.tranche_released",
        subject_type="reopen_tranche",
        subject_id=tranche.id,
        data={"amount": tranche.amount, "payout_batch": result.batch_id},
    )
    db.commit()
    return tranche


# --- The deadline: refund buyers if the business didn't reopen -------------------------------------


def _shares(total: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """Split `total` in proportion to `weights`, to the cent, with the rounding left-over on the largest."""
    whole = sum(weights, Decimal(0))
    if not weights or whole <= 0:
        return [Decimal(0)] * len(weights)
    shares = [(total * w / whole).quantize(CENT, rounding=ROUND_DOWN) for w in weights]
    shares[max(range(len(weights)), key=lambda i: weights[i])] += total - sum(shares, Decimal(0))
    return shares


def _refund_sales(card: GiftCard, share: Decimal) -> None:
    """Spread a regular's refund over their monthly payments, newest first."""
    left = share
    for payment in reversed(card.payments):
        amount = min(left, payment.amount - payment.refunded_amount)
        if amount <= 0:
            continue
        if not payment.paypal_sale_id.startswith("DEMO-"):
            subscriptions.refund_sale(payment.paypal_sale_id, amount)
        payment.refunded_amount += amount
        left -= amount
        if left <= 0:
            return


def refund_campaign(db: Session, campaign: ReopenCampaign, reason: str, actor: User | None = None) -> int:
    """Return what's left in escrow to buyers, in proportion to what they paid. Returns cards refunded."""
    for regular in db.scalars(select(ReopenRegular).where(ReopenRegular.campaign_id == campaign.id)):
        if regular.status == "active" and regular.paypal_subscription_id:
            try:
                subscriptions.cancel(regular.paypal_subscription_id, f"{campaign.business.name} did not reopen in time")
            except PayPalError:
                continue  # tried again at the next deadline check
            regular.status = "cancelled"
    cards = [c for c in campaign.cards if c.status == "active" and c.amount_paid > 0]
    held = escrow_balance(db, campaign.id)
    refunded = 0
    for card, share in zip(
        cards,
        _shares(min(held, sum((c.amount_paid for c in cards), Decimal(0))), [c.amount_paid for c in cards]),
        strict=True,
    ):
        if share > 0 and card.payments:  # a regular: refund across their monthly payments
            try:
                _refund_sales(card, share)
            except PayPalError:
                continue
        elif share > 0 and card.paypal_capture_id and not card.paypal_capture_id.startswith("DEMO-"):
            try:
                orders.refund_capture(card.paypal_capture_id, None if share >= card.amount_paid else share)
            except ErrorException:
                continue  # left active; the next deadline check retries it (the request id prevents doubles)
        if share > 0:
            ledger.post(
                db,
                kind="refund",
                description=f"Refund: {campaign.business.name} didn't reopen in time",
                paypal_ref=f"giftcard-refund-{card.id}",
                meta={"gift_card_id": card.id, "campaign_id": campaign.id},
                lines={escrow_account(campaign.id): share, ledger.CASH: -share},
            )
        card.status, card.refunded_amount, card.balance = "refunded", share, Decimal(0)
        refunded += 1
    if all(c.status != "active" for c in campaign.cards):
        campaign.status, campaign.refunded_at = "refunded", now()
    audit.record(
        db,
        actor_user_id=actor.id if actor else None,
        action="reopen.refunded",
        subject_type="reopen_campaign",
        subject_id=campaign.id,
        data={"reason": reason, "cards": refunded, "escrow": held},
    )
    db.commit()
    return refunded


def run_deadlines(db: Session, actor: User | None = None) -> list[int]:
    """Refund every live campaign whose reopening date has passed. Runs at start-up and on demand
    (Render's free plan has no cron)."""
    overdue = [
        c
        for c in db.scalars(select(ReopenCampaign).where(ReopenCampaign.status == "live"))
        if _aware(c.reopen_by) < now()
    ]
    for campaign in overdue:
        refund_campaign(db, campaign, f"Not reopened by {_aware(campaign.reopen_by):%b %d, %Y}", actor)
    return [c.id for c in overdue]


# --- Regulars: monthly pre-payments through PayPal Subscriptions ------------------------------------


def start_regular(
    db: Session, campaign: ReopenCampaign, buyer_name: str | None, buyer: User | None, return_url: str
) -> tuple[ReopenRegular, str | None]:
    """A pending regular with an empty card, and the PayPal link where the person approves the subscription."""
    if campaign.status != "live" or now() >= _aware(campaign.reopen_by):
        raise ReopenError("This Reopen Fund is not taking new regulars right now")
    business = campaign.business
    card = GiftCard(
        campaign_id=campaign.id,
        code=new_code(business),
        buyer_name=(buyer_name or "").strip()[:120] or None,
        buyer_user_id=buyer.id if buyer else None,
        amount_paid=Decimal(0),
        face_value=Decimal(0),
        payment_method="paypal",
    )
    db.add(card)
    db.flush()
    regular = ReopenRegular(
        campaign_id=campaign.id, gift_card_id=card.id, buyer_name=card.buyer_name, buyer_user_id=card.buyer_user_id
    )
    db.add(regular)
    db.flush()
    try:
        if campaign.paypal_plan_id is None:
            campaign.paypal_plan_id = subscriptions.create_plan(
                name=f"{business.name} regulars",
                description=f"Hearthline Reopen Fund: ${campaign.regular_monthly:.0f} a month for "
                f"{campaign.regular_months} months, added to your gift card",
                amount=campaign.regular_monthly,
                months=campaign.regular_months,
                request_id=f"reopen-plan-{campaign.id}",
            )
        back = f"{return_url}?kind=regular&id={regular.id}&t={buyer_token('regular', regular.id)}"
        sub = subscriptions.subscribe(
            plan_id=campaign.paypal_plan_id,
            custom_id=f"{REGULAR_PREFIX}{regular.id}",
            brand="Hearthline",
            return_url=back,
            cancel_url=back + "&cancelled=1",
        )
    except PayPalError as e:
        db.rollback()
        raise ReopenError(f"PayPal could not start the subscription ({e.status}). Try again in a moment.") from e
    regular.paypal_subscription_id = sub.id
    db.commit()
    return regular, sub.approval_url


def record_payment(db: Session, regular: ReopenRegular, sale_id: str, gross: Decimal, fee: Decimal) -> bool:
    """One monthly payment: it goes into escrow and its value (with the bonus) onto the card. Safe twice."""
    if db.scalar(select(GiftCardPayment.id).where(GiftCardPayment.paypal_sale_id == sale_id)):
        return False
    card, campaign = regular.card, regular.campaign
    value = (gross * (100 + campaign.bonus_percent) / 100).quantize(CENT)
    card.payments.append(GiftCardPayment(paypal_sale_id=sale_id, amount=gross, fee=fee))
    card.amount_paid += gross
    card.face_value += value
    card.balance += value
    card.status, card.activated_at = "active", card.activated_at or now()
    campaign.raised += gross
    ledger.post(
        db,
        kind="gift_card",
        description=f"Regular's monthly payment to {campaign.business.name}",
        paypal_ref=sale_id,
        meta={"gift_card_id": card.id, "campaign_id": campaign.id, "regular_id": regular.id},
        lines={ledger.CASH: gross - fee, ledger.FEES: fee, escrow_account(campaign.id): -gross},
    )
    audit.record(
        db,
        actor_user_id=regular.buyer_user_id,
        action="reopen.regular_paid",
        subject_type="gift_card",
        subject_id=card.id,
        data={"sale_id": sale_id, "amount": gross},
    )
    db.commit()
    return True


def sync_regular(db: Session, regular: ReopenRegular) -> ReopenRegular:
    """Ask PayPal where the subscription stands and record payments we have not seen (webhooks also do)."""
    if not regular.paypal_subscription_id:
        return regular
    try:
        state = subscriptions.status(regular.paypal_subscription_id)
        payments = subscriptions.payments(regular.paypal_subscription_id)
    except PayPalError as e:
        raise ReopenError(f"PayPal could not report on the subscription ({e.status})") from e
    if state in {"ACTIVE", "APPROVED"} and regular.status == "pending":
        regular.status, regular.activated_at = "active", now()
    elif state in {"CANCELLED", "EXPIRED", "SUSPENDED"}:
        regular.status = state.lower()
    db.commit()
    for sale_id, gross, fee in payments:
        record_payment(db, regular, sale_id, gross, fee)
    return regular


@on("PAYMENT.SALE.COMPLETED")
def on_sale_completed(db: Session, resource: dict) -> None:
    subscription_id = resource.get("billing_agreement_id")
    regular = db.scalar(select(ReopenRegular).where(ReopenRegular.paypal_subscription_id == subscription_id))
    if regular is None:
        return
    if regular.status == "pending":
        regular.status, regular.activated_at = "active", now()
    record_payment(
        db,
        regular,
        resource["id"],
        Decimal(resource["amount"]["total"]),
        Decimal(resource.get("transaction_fee", {}).get("value", "0")),
    )


def _on_subscription_ended(db: Session, resource: dict) -> None:
    regular = db.scalar(select(ReopenRegular).where(ReopenRegular.paypal_subscription_id == resource.get("id")))
    if regular is not None:
        regular.status = resource.get("status", "CANCELLED").lower()
        db.commit()


for _event in ("BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.EXPIRED", "BILLING.SUBSCRIPTION.SUSPENDED"):
    on(_event)(_on_subscription_ended)
