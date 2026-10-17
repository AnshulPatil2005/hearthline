"""Batch cash aid: many households, one PayPal Payouts call, two people.

- The batch is built on the server from the Command Center's filter. The browser never sends a list of
  households or amounts per household; it sends the filter and the amount for each damage level.
- Each household gets the amount for its damage level, but never more than it still needs.
- Households are left out (and the reason counted) if they aren't verified to level 2, have no PayPal
  account, share a PayPal account with another household, got cash aid in the last 14 days, or are already
  in a batch waiting for approval.
- The person who prepares a batch can't approve it. Eligibility is checked again at approval time.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, command, ledger
from app.models import (
    AidBatch,
    AidBatchItem,
    Household,
    LedgerAccount,
    LedgerPosting,
    LedgerTransaction,
    User,
    now,
)
from app.paypal import payouts, webhooks
from app.paypal.rest import PayPalError

DEFAULT_AMOUNTS = {"destroyed": 1000, "major": 750, "minor": 400, "affected": 200}
MIN_PAYMENT = Decimal("25")
MAX_PAYMENT = Decimal("5000")
RECENT_AID_DAYS = 14
MAX_ITEMS = 5000  # PayPal allows 15,000 payments per batch
# PayPal statuses after which the money is back in our account.
MONEY_RETURNED = {"RETURNED", "FAILED", "REFUNDED", "REVERSED", "BLOCKED", "DENIED"}
OPEN = ("awaiting_approval", "failed")


class BatchError(ValueError):
    pass


@dataclass
class Candidate:
    household_id: int
    name: str
    damage_level: str
    amount: Decimal
    receiver: str


def _amounts(raw: dict) -> dict[str, Decimal]:
    out = {}
    for level in DEFAULT_AMOUNTS:
        value = Decimal(str(raw.get(level, 0) or 0)).quantize(Decimal("1"))
        if value < 0 or value > MAX_PAYMENT:
            raise BatchError(f"Amounts must be between $0 and ${MAX_PAYMENT:,.0f}")
        out[level] = value
    return out


def _recent_aid(db: Session) -> set[int]:
    since = now() - timedelta(days=RECENT_AID_DAYS)
    q = (
        select(LedgerTransaction.household_id)
        .join(LedgerPosting, LedgerPosting.transaction_id == LedgerTransaction.id)
        .join(LedgerAccount, LedgerAccount.id == LedgerPosting.account_id)
        .where(LedgerAccount.code == ledger.CASH_AID, LedgerPosting.amount > 0, LedgerTransaction.created_at >= since)
    )
    return {hid for (hid,) in db.execute(q.distinct()) if hid is not None}


def _shared_paypal(db: Session) -> set[str]:
    q = (
        select(Household.payout_email)
        .where(Household.payout_email.is_not(None))
        .group_by(Household.payout_email)
        .having(func.count() > 1)
    )
    return {e for (e,) in db.execute(q)}


def _in_open_batch(db: Session, except_batch: int | None = None) -> set[int]:
    q = (
        select(AidBatchItem.household_id)
        .join(AidBatch)
        .where(AidBatch.status.in_(OPEN), AidBatchItem.status == "queued")
    )
    if except_batch is not None:
        q = q.where(AidBatch.id != except_batch)
    return {hid for (hid,) in db.execute(q)}


def _exclusion(
    level: int, email: str | None, hid: int, shared: set[str], recent: set[int], in_batch: set[int]
) -> str | None:
    if level < 2:
        return "not_verified"
    if not email:
        return "no_paypal"
    if email in shared:
        return "shared_paypal"
    if hid in recent:
        return "recent_aid"
    if hid in in_batch:
        return "in_open_batch"
    return None


def plan(db: Session, filter_model: dict | None, amounts: dict) -> tuple[list[Candidate], Counter]:
    """Who would be paid, and how many were left out for each reason."""
    per_level = _amounts(amounts)
    hh = command._households()
    rows = db.execute(
        select(hh.c.id, hh.c.name, hh.c.damage_level, hh.c.verification_level, hh.c.unmet_need)
        .where(*command._where(hh, filter_model))
        .order_by(hh.c.unmet_need.desc(), hh.c.id)
    ).all()
    ids = [r.id for r in rows]
    emails = {
        hid: email
        for hid, email in db.execute(select(Household.id, Household.payout_email).where(Household.id.in_(ids)))
    }
    shared, recent, in_batch = _shared_paypal(db), _recent_aid(db), _in_open_batch(db)
    chosen, excluded = [], Counter()
    for r in rows:
        reason = _exclusion(r.verification_level, emails.get(r.id), r.id, shared, recent, in_batch)
        amount = min(per_level.get(r.damage_level, Decimal(0)), Decimal(str(r.unmet_need or 0))).quantize(Decimal("1"))
        if reason is None and amount < MIN_PAYMENT:
            reason = "no_need"
        if reason:
            excluded[reason] += 1
        else:
            chosen.append(Candidate(r.id, r.name, r.damage_level, amount, emails[r.id]))
    return chosen, excluded


def preview(db: Session, filter_model: dict | None, amounts: dict) -> dict:
    chosen, excluded = plan(db, filter_model, amounts)
    by_damage: dict[str, dict] = {}
    for c in chosen:
        d = by_damage.setdefault(c.damage_level, {"households": 0, "amount": Decimal(0)})
        d["households"] += 1
        d["amount"] += c.amount
    return {
        "households": len(chosen),
        "total": f"{sum((c.amount for c in chosen), Decimal(0)):.2f}",
        "by_damage": {k: {"households": v["households"], "amount": f"{v['amount']:.2f}"} for k, v in by_damage.items()},
        "excluded": dict(excluded),
        "too_many": len(chosen) > MAX_ITEMS,
    }


def create(db: Session, creator: User, title: str, filter_model: dict | None, amounts: dict) -> AidBatch:
    chosen, excluded = plan(db, filter_model, amounts)
    if not chosen:
        raise BatchError("No household in this view can receive cash aid right now")
    if len(chosen) > MAX_ITEMS:
        raise BatchError(f"A batch can pay at most {MAX_ITEMS:,} households; narrow the filter")
    batch = AidBatch(
        title=title,
        created_by_user_id=creator.id,
        rule={"filter_model": filter_model or {}, "amounts": {k: str(v) for k, v in _amounts(amounts).items()}},
        total_amount=sum((c.amount for c in chosen), Decimal(0)),
    )
    batch.items = [AidBatchItem(household_id=c.household_id, amount=c.amount, receiver=c.receiver) for c in chosen]
    db.add(batch)
    db.flush()
    audit.record(
        db,
        actor_user_id=creator.id,
        action="aid_batch.created",
        subject_type="aid_batch",
        subject_id=batch.id,
        data={"households": len(chosen), "total": batch.total_amount, "excluded": dict(excluded)},
    )
    db.commit()
    return batch


def _check_second_person(batch: AidBatch, decider: User) -> None:
    if decider.id == batch.created_by_user_id:
        raise BatchError("A second person must approve a batch; the person who prepared it can't")
    if batch.status not in OPEN:
        raise BatchError(f"This batch is {batch.status}")


def approve(db: Session, batch: AidBatch, approver: User) -> AidBatch:
    """Second person approves: re-check every household, then pay them all in one Payouts call."""
    _check_second_person(batch, approver)
    shared, recent, in_batch = _shared_paypal(db), _recent_aid(db), _in_open_batch(db, except_batch=batch.id)
    for item in batch.items:
        if item.status != "queued":
            continue
        h = item.household
        reason = _exclusion(h.verification_level, h.payout_email, h.id, shared, recent, in_batch)
        if reason is None and h.payout_email != item.receiver:
            reason = "paypal_changed"
        if reason:
            item.status, item.note = "skipped", reason
    to_pay = [i for i in batch.items if i.status == "queued"]
    batch.decided_by_user_id, batch.decided_at = approver.id, now()
    if not to_pay:
        batch.status, batch.error = "failed", "No household in this batch can be paid any more"
        db.commit()
        return batch
    try:
        result = payouts.send_payouts(
            [(i.receiver, i.amount, "Cash aid from the Sablewood Relief Network", i.sender_item_id) for i in to_pay],
            batch_id=payouts.batch_id_for("aidbatch", batch.id, batch.created_at),
            subject="You have received disaster cash aid",
        )
    except PayPalError as e:  # nothing was sent; the batch stays open so it can be retried
        batch.status, batch.error = "failed", payouts.failure_reason(e, "this batch")
        audit.record(
            db,
            actor_user_id=approver.id,
            action="aid_batch.payout_failed",
            subject_type="aid_batch",
            subject_id=batch.id,
            data={"error": batch.error},
        )
        db.commit()
        return batch
    for item in to_pay:
        item.status = "PENDING"
        ledger.post(
            db,
            kind="payout",
            description=f"Cash aid (batch #{batch.id}) for {item.household.name}",
            household_id=item.household_id,
            paypal_ref=item.sender_item_id,
            meta={"aid_batch_id": batch.id, "payout_batch_id": result.batch_id},
            lines={ledger.CASH_AID: item.amount, ledger.CASH: -item.amount},
        )
    batch.status, batch.error, batch.paypal_batch_id = "sent", None, result.batch_id
    batch.total_amount = sum((i.amount for i in to_pay), Decimal(0))
    audit.record(
        db,
        actor_user_id=approver.id,
        action="aid_batch.approved",
        subject_type="aid_batch",
        subject_id=batch.id,
        data={"households": len(to_pay), "total": batch.total_amount, "payout_batch": result.batch_id},
    )
    db.commit()
    return batch


def reject(db: Session, batch: AidBatch, decider: User, reason: str) -> AidBatch:
    _check_second_person(batch, decider)
    batch.status, batch.decision_note = "rejected", reason
    batch.decided_by_user_id, batch.decided_at = decider.id, now()
    audit.record(
        db,
        actor_user_id=decider.id,
        action="aid_batch.rejected",
        subject_type="aid_batch",
        subject_id=batch.id,
        data={"reason": reason},
    )
    db.commit()
    return batch


def apply_item_status(db: Session, sender_item_id: str, payout_item_id: str | None, status: str) -> bool:
    """Record PayPal's latest status for one payment. If the money came back, return it to the relief fund."""
    if not sender_item_id.startswith("aidbatch-"):
        return False
    _, batch_id, household_id = sender_item_id.split("-")
    item = db.scalar(
        select(AidBatchItem).where(
            AidBatchItem.batch_id == int(batch_id), AidBatchItem.household_id == int(household_id)
        )
    )
    if item is None:
        return False
    was_returned = item.status in MONEY_RETURNED
    item.status, item.payout_item_id = status, payout_item_id or item.payout_item_id
    if status in MONEY_RETURNED and not was_returned:
        ledger.post(
            db,
            kind="refund",
            description=f"Cash aid returned by PayPal ({status.lower()}) for {item.household.name}",
            household_id=item.household_id,
            paypal_ref=f"{sender_item_id}-returned",
            meta={"aid_batch_id": item.batch_id},
            lines={ledger.CASH: item.amount, ledger.CASH_AID: -item.amount},
        )
    return True


def refresh(db: Session, batch: AidBatch) -> AidBatch:
    """Ask PayPal where each payment stands (webhooks do this too, when PayPal can reach us)."""
    if not batch.paypal_batch_id:
        raise BatchError("This batch hasn't been sent to PayPal")
    try:
        statuses = payouts.batch_items(batch.paypal_batch_id)
    except PayPalError as e:
        raise BatchError(f"PayPal couldn't report on this batch ({e.status}). Try again in a moment.") from e
    for s in statuses:
        apply_item_status(db, s.sender_item_id, s.payout_item_id, s.status)
    db.commit()
    return batch


def _on_item_event(db: Session, resource: dict) -> None:
    apply_item_status(
        db,
        resource.get("payout_item", {}).get("sender_item_id", ""),
        resource.get("payout_item_id"),
        resource.get("transaction_status", "PENDING"),
    )


# PayPal's payout item events. (REVERSED is an item status PayPal reports, but there is no webhook event for it.)
for _event in (
    "SUCCEEDED",
    "UNCLAIMED",
    "FAILED",
    "RETURNED",
    "BLOCKED",
    "REFUNDED",
    "DENIED",
    "HELD",
    "CANCELED",
):
    webhooks.on(f"PAYMENT.PAYOUTS-ITEM.{_event}")(_on_item_event)
