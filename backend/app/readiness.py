"""The readiness fund: monthly gifts through PayPal Subscriptions, given before any disaster.

First-72-hours aid draws on it, so the cash is already there when a warning comes. Each monthly payment PayPal
collects is credited to the fund (`liabilities:readiness_fund`); when a first-72-hours batch is paid, the part the
fund covers is released from it (`income:readiness_released`), and the rest comes from the organization's general
cash aid. The fund's balance is the ledger's, so it always matches the books.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, ledger
from app.models import (
    AidBatch,
    LedgerAccount,
    LedgerPosting,
    LedgerTransaction,
    ReadinessGiver,
    ReadinessPayment,
    ReadinessPlan,
    User,
    now,
)
from app.paypal import subscriptions
from app.paypal.rest import PayPalError
from app.paypal.webhooks import on

FUND = "liabilities:readiness_fund"
RELEASED = "income:readiness_released"
TIERS = (Decimal("10"), Decimal("25"), Decimal("50"))
CUSTOM_PREFIX = "readiness-"
ledger.ACCOUNT_DEFAULTS.setdefault(FUND, ("Readiness fund: monthly gifts held for first-72-hours aid", "liability"))
ledger.ACCOUNT_DEFAULTS.setdefault(RELEASED, ("Readiness fund released for first-72-hours aid", "income"))


class ReadinessError(ValueError):
    pass


@dataclass(frozen=True)
class Pool:
    balance: Decimal  # ready to pay now
    givers: int  # active monthly givers
    monthly: Decimal  # what they give each month, together
    released: Decimal  # paid to families from the fund so far
    batches: int  # first-72-hours batches it has paid into


def pool(db: Session) -> Pool:
    active = select(ReadinessGiver).where(ReadinessGiver.status == "active").subquery()
    givers, monthly = db.execute(select(func.count(active.c.id), func.coalesce(func.sum(active.c.monthly), 0))).one()
    released_rows = db.execute(
        select(func.coalesce(func.sum(LedgerPosting.amount), 0), func.count(LedgerPosting.id))
        .join(LedgerAccount)
        .where(LedgerAccount.code == RELEASED)
    ).one()
    return Pool(
        balance=-ledger.balance(db, FUND),
        givers=givers,
        monthly=Decimal(monthly).quantize(Decimal("0.01")),
        released=-Decimal(released_rows[0]).quantize(Decimal("0.01")),
        batches=released_rows[1],
    )


def covers(db: Session, total: Decimal) -> Decimal:
    """How much of a first-72-hours batch the fund can pay."""
    return max(min(pool(db).balance, total), Decimal(0))


# --- Giving monthly ---------------------------------------------------------------------------------------------------


def _plan(db: Session, monthly: Decimal) -> str:
    plan = db.scalar(select(ReadinessPlan).where(ReadinessPlan.monthly == monthly))
    if plan is None:
        plan_id = subscriptions.create_plan(
            name=f"Hearthline readiness fund: ${monthly:.0f} a month",
            description=f"${monthly:.0f} a month to Hearthline's readiness fund, which pays families who prepared "
            "within hours of an official disaster warning",
            amount=monthly,
            months=0,  # until the giver stops
            request_id=f"readiness-plan-{monthly:.0f}",
        )
        plan = ReadinessPlan(monthly=monthly, paypal_plan_id=plan_id)
        db.add(plan)
        db.flush()
    return plan.paypal_plan_id


def start(db: Session, user: User, monthly: Decimal, return_url: str) -> tuple[ReadinessGiver, str | None]:
    """A pending monthly gift, and the PayPal link where the person approves the subscription."""
    if monthly not in TIERS:
        raise ReadinessError(f"Choose one of ${', $'.join(f'{t:.0f}' for t in TIERS)} a month")
    if db.scalar(select(ReadinessGiver).where(ReadinessGiver.user_id == user.id, ReadinessGiver.status == "active")):
        raise ReadinessError("You already give monthly to the readiness fund")
    giver = ReadinessGiver(user_id=user.id, name=user.name, monthly=monthly)
    db.add(giver)
    db.flush()
    try:
        back = f"{return_url}?id={giver.id}"
        sub = subscriptions.subscribe(
            plan_id=_plan(db, monthly),
            custom_id=f"{CUSTOM_PREFIX}{giver.id}",
            brand="Hearthline",
            return_url=back,
            cancel_url=back + "&cancelled=1",
        )
    except PayPalError as e:
        db.rollback()
        raise ReadinessError(f"PayPal could not start the monthly gift ({e.status}). Try again in a moment.") from e
    giver.paypal_subscription_id = sub.id
    audit.record(
        db,
        actor_user_id=user.id,
        action="readiness.started",
        subject_type="readiness_giver",
        subject_id=giver.id,
        data={"monthly": monthly, "subscription": sub.id},
    )
    db.commit()
    return giver, sub.approval_url


def record_payment(db: Session, giver: ReadinessGiver, sale_id: str, gross: Decimal, fee: Decimal) -> bool:
    """One monthly payment into the fund. Safe twice (webhooks are retried, and syncing finds the same sale)."""
    if db.scalar(select(ReadinessPayment.id).where(ReadinessPayment.paypal_sale_id == sale_id)):
        return False
    giver.payments.append(ReadinessPayment(paypal_sale_id=sale_id, amount=gross, fee=fee))
    ledger.post(
        db,
        kind="readiness_gift",
        description=f"Monthly gift to the readiness fund from {giver.name}",
        paypal_ref=sale_id,
        meta={"readiness_giver_id": giver.id},
        lines={ledger.CASH: gross - fee, ledger.FEES: fee, FUND: -gross},
    )
    db.commit()
    return True


def sync(db: Session, giver: ReadinessGiver) -> ReadinessGiver:
    """Ask PayPal where the subscription stands and record payments not seen yet (webhooks do too)."""
    if not giver.paypal_subscription_id:
        return giver
    try:
        state = subscriptions.status(giver.paypal_subscription_id)
        payments = subscriptions.payments(giver.paypal_subscription_id)
    except PayPalError as e:
        raise ReadinessError(f"PayPal could not report on the monthly gift ({e.status})") from e
    _set_state(giver, state)
    db.commit()
    for sale_id, gross, fee in payments:
        record_payment(db, giver, sale_id, gross, fee)
    return giver


def _set_state(giver: ReadinessGiver, state: str) -> None:
    if state in {"ACTIVE", "APPROVED"} and giver.status == "pending":
        giver.status, giver.activated_at = "active", now()
    elif state in {"CANCELLED", "EXPIRED", "SUSPENDED"} and giver.status != state.lower():
        giver.status, giver.ended_at = state.lower(), now()


def stop(db: Session, giver: ReadinessGiver, user: User) -> ReadinessGiver:
    if giver.status not in {"active", "pending"}:
        raise ReadinessError(f"This monthly gift is already {giver.status}")
    if giver.paypal_subscription_id:
        try:
            # One nobody approved can't be cancelled at PayPal; it lapses by itself
            if subscriptions.status(giver.paypal_subscription_id) not in {"APPROVAL_PENDING", "CANCELLED", "EXPIRED"}:
                subscriptions.cancel(giver.paypal_subscription_id, "The giver stopped their monthly gift")
        except PayPalError as e:
            raise ReadinessError(f"PayPal could not stop the monthly gift ({e.status}). Try again.") from e
    giver.status, giver.ended_at = "cancelled", now()
    audit.record(
        db, actor_user_id=user.id, action="readiness.stopped", subject_type="readiness_giver", subject_id=giver.id
    )
    db.commit()
    return giver


@on("PAYMENT.SALE.COMPLETED")
def on_sale_completed(db: Session, resource: dict) -> None:
    giver = db.scalar(
        select(ReadinessGiver).where(ReadinessGiver.paypal_subscription_id == resource.get("billing_agreement_id"))
    )
    if giver is None:
        return
    _set_state(giver, "ACTIVE")
    record_payment(
        db,
        giver,
        resource["id"],
        Decimal(resource["amount"]["total"]),
        Decimal(resource.get("transaction_fee", {}).get("value", "0")),
    )


def _on_subscription_ended(db: Session, resource: dict) -> None:
    giver = db.scalar(select(ReadinessGiver).where(ReadinessGiver.paypal_subscription_id == resource.get("id")))
    if giver is not None:
        _set_state(giver, resource.get("status", "CANCELLED"))
        db.commit()


for _event in ("BILLING.SUBSCRIPTION.CANCELLED", "BILLING.SUBSCRIPTION.EXPIRED", "BILLING.SUBSCRIPTION.SUSPENDED"):
    on(_event)(_on_subscription_ended)


# --- Paying first-72-hours aid ----------------------------------------------------------------------------------------


def release(db: Session, batch: AidBatch, actor: User) -> Decimal:
    """After a first-72-hours batch is sent, release the part of it the fund covers. Returns that amount."""
    if batch.status != "sent":
        return Decimal(0)
    already = db.scalar(
        select(LedgerTransaction.id).where(LedgerTransaction.paypal_ref == f"readiness-release-{batch.id}")
    )
    if already:
        return Decimal(batch.rule.get("readiness_covered", "0"))
    covered = covers(db, batch.total_amount)
    if covered > 0:
        ledger.post(
            db,
            kind="readiness_release",
            description=f"Readiness fund pays for first-72-hours aid (batch #{batch.id})",
            paypal_ref=f"readiness-release-{batch.id}",  # an internal key, so a retry can't release twice
            meta={"aid_batch_id": batch.id},
            lines={FUND: covered, RELEASED: -covered},
        )
    batch.rule = {**batch.rule, "readiness_covered": str(covered)}
    audit.record(
        db,
        actor_user_id=actor.id,
        action="readiness.released",
        subject_type="aid_batch",
        subject_id=batch.id,
        data={"covered": covered, "total": batch.total_amount},
    )
    db.commit()
    return covered
