"""Sablewood Mercantile: a general store the fire closed, which reopened with its Reopen Fund (demo data). It sells
some of what families need, so the Shopper buys there before web stores. Start-up only and idempotent."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Business, LocalOffer, ReopenCampaign, ReopenTranche, User, now

# (title, category, price): what the store stocks that families on the registries need
CATALOG = [
    ("Twin mattress, 8-inch foam", "bedding", "219.00"),
    ("Metal twin bed frame", "furniture", "119.00"),
    ("Kids' insulated winter jacket", "clothing", "69.00"),
    ("Steel-toe work boots", "clothing", "129.00"),
    ("Kitchen starter set: pots, pans, plates, utensils", "kitchenware", "169.00"),
    ("Dog crate with bed, medium", "other", "89.00"),
]


def seed_local_store(db: Session) -> None:
    if db.scalar(select(Business.id).where(Business.slug == "sablewood-mercantile")) is not None:
        return
    rosa = db.scalar(select(User).where(User.name == "Rosa Delgado"))
    sam = db.scalar(select(User).where(User.name == "Sam Whitfield"))
    if rosa is None or sam is None:
        return
    today = now().replace(hour=9, minute=0, second=0, microsecond=0)
    store = Business(
        owner_user_id=rosa.id,
        name="Sablewood Mercantile",
        slug="sablewood-mercantile",
        kind="retail",
        address_line="15 Main St",
        city="Sablewood",
        state="CA",
        lat=38.705,
        lng=-120.634,
        license_number="SBW-BL-10077",
        payout_email="rosa.delgado@business.example.com",
        verification="verified",
        verified_by_user_id=sam.id,
        verification_note="City license checked; the store is inside the burn area.",
        story=(
            "The general store on Main Street since 1952: bedding, clothes, kitchen things, hardware. Smoke and water "
            "closed us for three weeks. Our regulars' gift cards paid for the cleanup, and we're open again."
        ),
    )
    db.add(store)
    db.flush()
    campaign = ReopenCampaign(
        business_id=store.id,
        goal_amount=Decimal("6000"),
        bonus_percent=10,
        raised=Decimal("6000"),
        reopen_by=today + timedelta(days=10),
        status="reopened",
        created_at=today - timedelta(days=21),
        reopened_at=today - timedelta(days=4),
    )
    for seq, (title, amount, start, released) in enumerate(
        [("Smoke cleanup and repairs", "4000", -20, 12), ("Restock the shelves", "2000", -10, 6)], start=1
    ):
        campaign.tranches.append(
            ReopenTranche(
                seq=seq,
                title=title,
                amount=Decimal(amount),
                start_date=today + timedelta(days=start),
                end_date=today + timedelta(days=start + 8),
                status="released",
                released_at=today - timedelta(days=released),
                paypal_ref=f"DEMO-TRANCHE-MERCANTILE-{seq}",
            )
        )
    store.campaigns.append(campaign)
    for title, category, price in CATALOG:
        db.add(LocalOffer(business_id=store.id, title=title, category=category, unit_price=Decimal(price)))
    db.commit()
