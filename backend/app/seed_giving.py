"""A donor's history for the demo (persona Marcus Chen). Start-up only and idempotent; no PayPal calls.

- He fully funded the Riveras' winter jackets; the Shopper bought them at Target and they were delivered.
- He gave $100 toward Maya's school laptop.
- He bought a $50 gift card from Moreno's Bakery.
"""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ledger, registry, reopen, shopping
from app.models import Business, Donation, GiftCard, Purchase, RegistryItem, User, now
from app.paypal.orders import Capture


def _give(db: Session, donor: User, item: RegistryItem, amount: Decimal, days_ago: int, message: str) -> None:
    donation = Donation(
        registry_id=item.registry_id,
        registry_item_id=item.id,
        donor_user_id=donor.id,
        donor_name=donor.name.split()[0],
        message=message,
        amount=amount,
        payment_method="venmo",
        paypal_order_id=f"DEMO-ORDER-GIVE-{item.id}",
        created_at=now() - timedelta(days=days_ago),
    )
    db.add(donation)
    db.commit()
    fee = (amount * Decimal("0.0349") + Decimal("0.49")).quantize(Decimal("0.01"))
    registry.apply_capture(
        db, donation, Capture(donation.paypal_order_id, f"DEMO-CAP-GIVE-{item.id}", "COMPLETED", amount, fee, "venmo")
    )
    donation.captured_at = donation.created_at


def seed_giving_demo(db: Session) -> None:
    marcus = db.scalar(select(User).where(User.name == "Marcus Chen"))
    if marcus is None or db.scalar(select(Donation.id).where(Donation.donor_user_id == marcus.id).limit(1)):
        return
    jackets = db.scalar(select(RegistryItem).where(RegistryItem.name == "Winter jackets for the kids"))
    laptop = db.scalar(select(RegistryItem).where(RegistryItem.name == "School laptop for Maya"))
    if jackets is None or laptop is None:
        return

    auto_shop = shopping.start_auto_shop
    shopping.start_auto_shop = lambda item_id: None  # start-up never runs the live Shopper
    try:
        _give(db, marcus, jackets, jackets.target_amount - jackets.funded_amount, 12, "Stay warm, Maya and Leo.")
        _give(db, marcus, laptop, Decimal("100.00"), 5, "For homework. Good luck this year!")
    finally:
        shopping.start_auto_shop = auto_shop

    # What the Shopper did with the jackets money (as it would have, minus the live calls).
    home_id = jackets.rebuild_registry.household_id
    bought = now() - timedelta(days=11)
    purchase = Purchase(
        household_id=home_id,
        registry_item_id=jackets.id,
        title="Kids' Insulated Puffer Jacket",
        retailer="target.com",
        url="https://www.target.com/",
        unit_price=Decimal("74.99"),
        quantity=2,
        total=Decimal("149.98"),
        status="delivered",
        ai_reasoning="Target's insulated puffer comes in sizes 8 and 12 and is rated for freezing weather, "
        "which suits two kids in the foothills this winter.",
        ai_confidence=0.88,
        candidates_considered=5,
        paypal_ref="DEMO-PURCHASE-JACKETS",
        carrier="UPS",
        tracking_number="1Z999AA10123456784",
        created_at=bought,
        paid_at=bought,
        policy_checks=[
            {"rule": rule, "passed": True, "detail": detail}
            for rule, detail in [
                ("funds_available", "$149.98 needed, $158.00 held for the household"),
                ("within_item_funding", "$149.98 vs $158.00 donated for this item"),
                ("per_item_limit", "limit $1,000.00 per purchase"),
                ("daily_limit", "$0.00 already spent today, limit $2,500.00"),
                ("category_allowed", "category 'clothing'"),
                ("known_retailer", "target.com is an approved retailer"),
                ("ships_to_verified_address", "ships only to the household's verified address"),
                ("price_sanity", "$74.99 vs $79.99 median of comparable offers"),
                ("no_price_gouging", "$74.99 now vs $79.99 before the declaration (-6%); the limit is +10%"),
            ]
        ],
    )
    db.add(purchase)
    ledger.record_spend(
        db,
        kind="purchase",
        household_id=home_id,
        amount=purchase.total,
        paypal_ref=purchase.paypal_ref,
        description=f"{purchase.title} x2 from {purchase.retailer}",
        meta={"registry_item_id": jackets.id},
    )
    jackets.status = "delivered"

    bakery = db.scalar(select(Business).where(Business.slug == "morenos-bakery"))
    campaign = reopen.current_campaign(bakery) if bakery else None
    if campaign is not None:
        card = GiftCard(
            campaign_id=campaign.id,
            code=reopen.new_code(bakery),
            buyer_name="Marcus",
            buyer_user_id=marcus.id,
            amount_paid=Decimal("50.00"),
            face_value=(Decimal("50.00") * (100 + campaign.bonus_percent) / 100).quantize(Decimal("0.01")),
            payment_method="paypal",
            status="active",
            paypal_capture_id="DEMO-CARD-MARCUS",
            created_at=now() - timedelta(days=3),
        )
        card.balance, card.activated_at = card.face_value, card.created_at
        db.add(card)
        db.flush()
        ledger.post(
            db,
            kind="gift_card",
            description=f"Gift card for {bakery.name}",
            paypal_ref=card.paypal_capture_id,
            meta={"gift_card_id": card.id, "campaign_id": campaign.id},
            lines={
                ledger.CASH: Decimal("47.76"),
                ledger.FEES: Decimal("2.24"),
                reopen.escrow_account(campaign.id): Decimal("-50.00"),
            },
        )
        campaign.raised += card.amount_paid
    db.commit()
