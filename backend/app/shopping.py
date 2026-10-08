"""Turns a funded registry item into a purchase: Shopper agent -> spending rules -> PayPal payment.

Runs automatically (in a background thread) when donations fully fund an item, or on demand.
"""

import logging
import statistics
import threading
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, geo, ledger, policy
from app.agents import shopper
from app.config import get_settings
from app.db import SessionLocal
from app.models import Household, Purchase, RegistryItem, now
from app.paypal import payouts

log = logging.getLogger(__name__)
STANDIN_RETAILER = "retailer-standin@example.com"  # sandbox: payouts to unknown emails stay UNCLAIMED


class ShoppingError(RuntimeError):
    pass


def retailer_payee(_domain: str) -> str:
    """Where money for a retailer goes. Decided here, never by the AI (no new payees).
    In the sandbox every approved retailer is one stand-in merchant account."""
    return get_settings().paypal_sandbox_retailer_email or STANDIN_RETAILER


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)  # SQLite returns naive datetimes


def spent_today(db: Session, household_id: int) -> Decimal:
    today = datetime.now(UTC).date()
    paid = db.scalars(select(Purchase).where(Purchase.household_id == household_id, Purchase.paid_at.is_not(None)))
    return sum((p.total for p in paid if _aware(p.paid_at).date() == today), Decimal(0))


def ships_to_verified_address(home: Household) -> bool:
    return bool(
        home.disaster_event and home.lat is not None and geo.in_zone(home.disaster_event.zone, home.lat, home.lng)
    )


def plan_purchase(db: Session, item: RegistryItem) -> Purchase:
    home = item.rebuild_registry.household
    budget_per_unit = (item.funded_amount / item.quantity).quantize(Decimal("0.01"))
    query = f"{item.name} {item.note}".strip()
    candidates = shopper.find_candidates(item.name, budget_per_unit)
    if not candidates:
        candidates = shopper.find_candidates(query, budget_per_unit)
    purchase = Purchase(
        household_id=home.id,
        registry_item_id=item.id,
        quantity=item.quantity,
        candidates_considered=len(candidates),
        title=item.name,
        retailer="",
        unit_price=Decimal(0),
        total=Decimal(0),
    )
    db.add(purchase)
    if not candidates:
        purchase.status, purchase.error = "failed", "No in-stock offers from approved retailers"
        db.commit()
        return purchase

    choice = shopper.choose(item.name, item.note, item.quantity, budget_per_unit, candidates)
    purchase.ai_reasoning = choice.reasoning[:1000]
    purchase.ai_confidence = choice.confidence
    if choice.choice < 0:
        purchase.status, purchase.error = "failed", "The Shopper found no offer that fits this need"
        db.commit()
        return purchase

    picked = candidates[choice.choice]
    purchase.channel3_product_id = picked.product_id
    purchase.title = picked.title[:300]
    purchase.retailer = picked.retailer
    purchase.url = picked.url[:600]
    purchase.unit_price = picked.unit_price
    purchase.total = picked.unit_price * item.quantity

    decision = policy.evaluate(
        policy.Proposal(
            total=purchase.total,
            category=item.category,
            retailer=picked.retailer,
            unit_price=picked.unit_price,
            comparable_median=Decimal(str(statistics.median(c.unit_price for c in candidates))),
            ai_confidence=choice.confidence,
        ),
        item_funded=item.funded_amount,
        available_funds=ledger.household_available(db, home.id),
        spent_today=spent_today(db, home.id),
        allowed_retailers=shopper.APPROVED_RETAILERS,
        ship_to_verified=ships_to_verified_address(home),
    )
    purchase.policy_checks = decision.as_json()
    purchase.status = (
        "blocked" if not decision.allowed else "awaiting_approval" if decision.needs_approval else "approved"
    )
    db.flush()
    audit.record(
        db,
        action=f"purchase.{purchase.status}",
        subject_type="purchase",
        subject_id=purchase.id,
        data={
            "item_id": item.id,
            "total": purchase.total,
            "retailer": purchase.retailer,
            "failed_rules": [c.rule for c in decision.checks if not c.passed],
        },
    )
    db.commit()
    if purchase.status == "approved":
        execute(db, purchase)
    return purchase


def execute(db: Session, purchase: Purchase, approved_by: int | None = None) -> Purchase:
    """Pay the retailer through PayPal and record the spend. Only for allowed proposals."""
    if purchase.status not in {"approved", "awaiting_approval"}:
        raise ShoppingError(f"Purchase is {purchase.status}")
    if not all(c["passed"] for c in purchase.policy_checks):
        raise ShoppingError("Purchase failed a spending rule")
    item = purchase.registry_item
    try:
        result = payouts.send_payouts(
            [
                (
                    retailer_payee(purchase.retailer),
                    purchase.total,
                    f"Hearthline order: {purchase.title}"[:200],
                    f"purchase-{purchase.id}",
                )
            ],
            batch_id=payouts.batch_id_for("purchase", purchase.id, purchase.created_at),
            subject="Hearthline purchase order",
        )
    except Exception as e:  # report on the purchase; nothing was posted to the ledger
        purchase.status, purchase.error = "failed", f"PayPal payout failed: {e}"[:500]
        db.commit()
        return purchase
    purchase.status = "paid"
    purchase.paypal_ref = result.batch_id
    purchase.paid_at = now()
    ledger.record_spend(
        db,
        kind="purchase",
        household_id=purchase.household_id,
        amount=purchase.total,
        paypal_ref=result.batch_id,
        description=f"Bought {purchase.title} from {purchase.retailer}",
        meta={"purchase_id": purchase.id, "registry_item_id": item.id if item else None},
    )
    if item is not None:
        item.status = "purchased"
    audit.record(
        db,
        actor_user_id=approved_by,
        action="purchase.paid",
        subject_type="purchase",
        subject_id=purchase.id,
        data={"total": purchase.total, "payout_batch": result.batch_id},
    )
    db.commit()
    return purchase


def shop_item(item_id: int) -> None:
    with SessionLocal() as db:
        item = db.get(RegistryItem, item_id)
        if item is None or item.status != "funded":
            return
        already = db.scalar(
            select(Purchase).where(
                Purchase.registry_item_id == item_id, Purchase.status.not_in(["failed", "rejected", "blocked"])
            )
        )
        if already is not None:
            return
        try:
            plan_purchase(db, item)
        except Exception:
            log.exception("Shopper failed for registry item %s", item_id)


def start_auto_shop(item_id: int) -> None:
    """Called when donations fully fund an item. Runs the Shopper without delaying the donor."""
    threading.Thread(target=shop_item, args=(item_id,), daemon=True).start()
