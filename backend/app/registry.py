"""Donation lifecycle shared by the browser capture call and the PayPal webhook (whichever arrives first)."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, ledger, shopping
from app.models import Donation, now
from app.paypal.orders import Capture
from app.paypal.webhooks import on

CUSTOM_ID_PREFIX = "donation:"


def apply_capture(db: Session, donation: Donation, capture: Capture) -> Donation:
    """Mark a donation captured, fund its item, and post it to the ledger. Safe to call twice."""
    if donation.status == "captured" or capture.status != "COMPLETED":
        return donation
    donation.status = "captured"
    donation.paypal_capture_id = capture.capture_id
    donation.fee = capture.fee
    donation.captured_at = now()
    if capture.payment_method == "venmo":
        donation.payment_method = "venmo"
    item = donation.item
    newly_funded = False
    if item is not None:
        item.funded_amount += donation.amount
        if item.funded_amount >= item.target_amount and item.status == "open":
            item.status = "funded"
            newly_funded = True
    household_id = donation.rebuild_registry.household_id
    ledger.record_donation(
        db,
        household_id=household_id,
        gross=capture.amount,
        fee=capture.fee,
        capture_id=capture.capture_id,
        description=f"Donation for {item.name}" if item else "Donation to the household fund",
        meta={"donation_id": donation.id, "registry_item_id": item.id if item else None},
    )
    audit.record(
        db,
        actor_user_id=donation.donor_user_id,
        action="donation.captured",
        subject_type="donation",
        subject_id=donation.id,
        data={
            "amount": donation.amount,
            "fee": capture.fee,
            "capture_id": capture.capture_id,
            "item_id": item.id if item else None,
            "method": donation.payment_method,
        },
    )
    db.commit()
    if newly_funded:
        shopping.start_auto_shop(item.id)  # the Shopper agent buys it in the background
    return donation


@on("PAYMENT.CAPTURE.COMPLETED")
def on_capture_completed(db: Session, resource: dict) -> None:
    """Backup path: the donor closed the tab before our capture call returned."""
    custom_id = resource.get("custom_id") or ""
    if not custom_id.startswith(CUSTOM_ID_PREFIX):
        return
    donation = db.get(Donation, int(custom_id.removeprefix(CUSTOM_ID_PREFIX)))
    if donation is None:
        return
    order_id = resource.get("supplementary_data", {}).get("related_ids", {}).get("order_id", donation.paypal_order_id)
    capture = Capture(
        order_id=order_id,
        capture_id=resource["id"],
        status=resource["status"],
        amount=Decimal(resource["amount"]["value"]),
        fee=Decimal(resource.get("seller_receivable_breakdown", {}).get("paypal_fee", {}).get("value", "0")),
        payment_method=donation.payment_method,
    )
    apply_capture(db, donation, capture)


def recent_donations(db: Session, registry_id: int, limit: int = 12) -> list[Donation]:
    return list(
        db.scalars(
            select(Donation)
            .where(Donation.registry_id == registry_id, Donation.status == "captured")
            .order_by(Donation.captured_at.desc())
            .limit(limit)
        )
    )
