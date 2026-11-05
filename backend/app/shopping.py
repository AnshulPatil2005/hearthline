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

from app import audit, gouging, ledger, local_first, marketplace, policy, trust
from app.agents import shopper
from app.config import get_settings
from app.db import SessionLocal
from app.models import Business, Donation, Household, Purchase, RegistryItem, now
from app.paypal import payouts, tracking
from app.paypal.rest import PayPalError

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
    """Inside the disaster zone and proven to be the family's home (a document or a caseworker's vouch). An address
    that is merely inside the zone could be anyone's."""
    return trust.in_disaster_zone(home) and bool(home.residence_verified or home.vouched_by_user_id)


def plan_purchase(db: Session, item: RegistryItem) -> Purchase:
    home = item.rebuild_registry.household
    budget_per_unit = (item.funded_amount / item.quantity).quantize(Decimal("0.01"))
    query = f"{item.name} {item.note}".strip()
    local = local_first.candidates(db, item, home, budget_per_unit)
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
    if not candidates and not local:
        purchase.status, purchase.error = "failed", "No in-stock offers from approved retailers"
        db.commit()
        return purchase

    # Price-gouging guard: offers priced more than 10% above their pre-disaster price are refused.
    verdicts: dict[str, gouging.Verdict] = {}
    event = home.disaster_event
    if gouging.protection_active(event):
        for c in candidates:
            _, verdicts[c.product_id] = gouging.watch_offer(
                db,
                event,
                product_id=c.product_id,
                title=c.title,
                seller=c.retailer,
                url=c.url,
                category=item.category,
                price=c.unit_price,
            )
        purchase.refused_offers = [
            {
                "title": c.title[:200],
                "retailer": c.retailer,
                "price": str(c.unit_price),
                "baseline": str(verdicts[c.product_id].baseline),
                "markup_percent": verdicts[c.product_id].markup_percent,
            }
            for c in candidates
            if verdicts[c.product_id].gouging
        ]
        candidates = [c for c in candidates if not verdicts[c.product_id].gouging]
        purchase.candidates_considered = len(candidates) + len(purchase.refused_offers)
        if not candidates and not local:
            purchase.status = "failed"
            purchase.error = "Every offer was more than 10% above its price before the disaster (price gouging)"
            db.commit()
            return purchase
    purchase.candidates_considered += len(local)

    # Local first: the AI judges fit at each local store and online; the stores' pricing agents quote over MCP; code
    # sets the most the Shopper will pay and decides.
    online = shopper.choose(item.name, item.note, item.quantity, budget_per_unit, candidates) if candidates else None
    online_pick = candidates[online.choice] if online and online.choice >= 0 else None
    pick: local_first.LocalPick | None = None
    local_note = ""
    fit = None
    if local:
        by_store: dict[str, list[tuple[shopper.Candidate, Business]]] = {}
        for candidate, business in local.values():
            by_store.setdefault(business.slug, []).append((candidate, business))
        asks, fits = [], {}
        for slug, offers in by_store.items():
            choice = shopper.choose(item.name, item.note, item.quantity, budget_per_unit, [c for c, _ in offers])
            if choice.choice >= 0 and choice.confidence >= local_first.MIN_FIT:
                chosen, business = offers[choice.choice]
                offer_id = int(chosen.product_id.removeprefix("local-"))
                asks.append(marketplace.Ask(slug, business.name, offer_id, chosen.title))
                fits[slug] = (choice, chosen, business.id)
        if asks:
            most, reason = local_first.limit(budget_per_unit, online_pick)
            note = item.note.strip().rstrip(".")
            need = item.name[:1].lower() + item.name[1:] + (f" ({note[:1].lower() + note[1:]})" if note else "")
            db.flush()
            quantity, item_id, purchase_id = item.quantity, item.id, purchase.id
            # The stores' agents record their quotes against this purchase on their own connection: commit, and touch
            # nothing in this session until they've answered (on SQLite a read here would block their writes).
            db.commit()
            outcome = marketplace.negotiate(
                asks,
                quantity=quantity,
                limit=most,
                need=need,
                competing=online_pick.unit_price if online_pick else None,
                reason=reason,
                registry_item_id=item_id,
                purchase_id=purchase_id,
            )
            purchase.negotiation = outcome.transcript
            if outcome.deal is not None:
                fit, chosen, business_id = fits[outcome.deal.store_slug]
                agreed = shopper.Candidate(
                    chosen.product_id, chosen.title, chosen.retailer, outcome.deal.unit_price, chosen.url
                )
                pick = local_first.LocalPick(agreed, db.get(Business, business_id), online_pick, outcome.summary)
            else:
                local_note = f" {outcome.summary}"

    choice = fit if pick else online
    if choice is None:
        purchase.status, purchase.error = "failed", "No local or online offer fits this need"
        db.commit()
        return purchase
    purchase.ai_reasoning = (choice.reasoning + (f" {local_first.note(pick)}" if pick else local_note))[:1000]
    purchase.ai_confidence = choice.confidence
    if pick is None and choice.choice < 0:
        purchase.status, purchase.error = "failed", "The Shopper found no offer that fits this need"
        db.commit()
        return purchase

    picked = pick.candidate if pick else candidates[choice.choice]
    purchase.channel3_product_id = None if pick else picked.product_id
    purchase.local_business_id = pick.business.id if pick else None
    purchase.title = picked.title[:300]
    purchase.retailer = picked.retailer
    purchase.url = picked.url[:600]
    purchase.unit_price = picked.unit_price
    purchase.total = picked.unit_price * item.quantity
    # Comparable offers: for a local pick, the local offers and the online offer the Shopper would otherwise buy (web
    # listings it judged not to fit, like a dog bed without the crate, would make the median meaninglessly low).
    comparable = [c for c, _ in local.values()] + ([online_pick] if online_pick else []) if pick else candidates

    decision = policy.evaluate(
        policy.Proposal(
            total=purchase.total,
            category=item.category,
            retailer=picked.retailer,
            unit_price=picked.unit_price,
            comparable_median=Decimal(str(statistics.median(c.unit_price for c in comparable))),
            ai_confidence=choice.confidence,
        ),
        gouging=verdicts.get(picked.product_id),
        item_funded=item.funded_amount,
        available_funds=ledger.household_available(db, home.id),
        spent_today=spent_today(db, home.id),
        allowed_retailers=shopper.APPROVED_RETAILERS | {b.name for _, b in local.values()},
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
    local = db.get(Business, purchase.local_business_id) if purchase.local_business_id else None
    if local is not None and not local.payout_email:
        raise ShoppingError(f"{local.name} hasn't connected a PayPal account yet")
    try:
        result = payouts.send_payouts(
            [
                (
                    local.payout_email if local else retailer_payee(purchase.retailer),
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
        description=f"Bought {purchase.title} from {purchase.retailer}{' (local business)' if local else ''}",
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


def share_tracking(db: Session, purchase: Purchase) -> int:
    """Put the shipment on each donor's PayPal payment for this item. Best effort: shipping never waits on it."""
    if purchase.registry_item_id is None or not purchase.tracking_number:
        return 0
    donations = db.scalars(
        select(Donation).where(Donation.registry_item_id == purchase.registry_item_id, Donation.status == "captured")
    )
    shared = 0
    for d in donations:
        if not d.paypal_order_id or not d.paypal_capture_id or d.paypal_capture_id.startswith("DEMO-"):
            continue
        try:
            tracking.add(d.paypal_order_id, d.paypal_capture_id, purchase.tracking_number, purchase.carrier or "OTHER")
            shared += 1
        except PayPalError:
            log.warning("Tracking not added to donation %s", d.id)
    return shared
