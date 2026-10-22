"""Local stores the Shopper buys from before web stores (demo data): Sablewood Mercantile, a general store the fire
closed, which reopened with its Reopen Fund, and Juniper Hardware & Home, which never closed. Each sells through a
pricing agent bound by its owner's rules (a floor under each list price, stock on hand, the owner's note), so the
Shopper's quotes are a real comparison. Start-up only and idempotent."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Business, LocalOffer, ReopenCampaign, ReopenTranche, Role, User, now

# (title, category, list price, floor, stock): what the stores stock that families on the registries need
CATALOG = [
    ("Twin mattress, 8-inch foam", "bedding", "219.00", "199.00", 4),
    ("Metal twin bed frame", "furniture", "129.00", "104.00", 6),
    ("Kids' insulated winter jacket", "clothing", "69.00", "59.00", 10),
    ("Steel-toe work boots", "clothing", "129.00", "112.00", 3),
    ("Kitchen starter set: pots, pans, plates, utensils", "kitchenware", "169.00", "149.00", 5),
    ("Dog crate with bed, medium", "other", "89.00", "79.00", 2),
]
MERCANTILE_NOTE = "We're a family store too. Families from the fire get the best price we can afford."

HARDWARE = [
    ("Twin mattress, medium firm", "bedding", "239.00", "215.00", 6),
    ("Steel platform bed frame, twin", "furniture", "114.00", "99.00", 8),
    ("Steel-toe work boots, waterproof", "clothing", "124.00", "112.00", 4),
    ("Kitchen essentials set: cookware, dishes, utensils", "kitchenware", "159.00", "139.00", 3),
]
HARDWARE_NOTE = "Match fair prices for families who lost their homes, but never sell below cost."


def _offers(db: Session, business: Business, catalog: list[tuple[str, str, str, str, int]]) -> None:
    for title, category, price, floor, stock in catalog:
        db.add(
            LocalOffer(
                business_id=business.id,
                title=title,
                category=category,
                unit_price=Decimal(price),
                floor_price=Decimal(floor),
                stock=stock,
            )
        )


def seed_hardware_store(db: Session) -> None:
    """Juniper Hardware & Home: open throughout (no Reopen Fund), a second local seller for the Shopper to compare."""
    if db.scalar(select(Business.id).where(Business.slug == "juniper-hardware")) is not None:
        return
    sam = db.scalar(select(User).where(User.name == "Sam Whitfield"))
    if sam is None:
        return
    owner = db.scalar(select(User).where(User.email == "ken.ito@business.example.com"))
    if owner is None:
        owner = User(email="ken.ito@business.example.com", name="Ken Ito", role=Role.BUSINESS, title="Business owner")
        db.add(owner)
        db.flush()
    store = Business(
        owner_user_id=owner.id,
        name="Juniper Hardware & Home",
        slug="juniper-hardware",
        kind="retail",
        address_line="402 Juniper Ave",
        city="Sablewood",
        state="CA",
        lat=38.709,
        lng=-120.641,
        license_number="SBW-BL-10342",
        payout_email="ken.ito@business.example.com",
        verification="verified",
        verified_by_user_id=sam.id,
        verification_note="City license checked; outside the burn area, open throughout.",
        story="Hardware, beds and kitchen basics on the north side of town. The fire stopped a block away.",
        agent_note=HARDWARE_NOTE,
    )
    db.add(store)
    db.flush()
    _offers(db, store, HARDWARE)
    db.commit()


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
        agent_note=MERCANTILE_NOTE,
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
    _offers(db, store, CATALOG)
    db.commit()
