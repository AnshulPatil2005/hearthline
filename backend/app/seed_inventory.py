"""The Riveras' home inventory, scanned room by room about two months before the fire (demo data).
Start-up only and idempotent. Prices are what the family entered, not Channel3 matches."""

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import trust
from app.models import EvidenceLevel, Household, Item, Room, now

# room -> (name, category, quantity, unit price)
ROOMS = {
    "Living room": [
        ("3-seat grey fabric sofa", "furniture", 1, "1299.00"),
        ("65-inch 4K smart TV", "electronics", 1, "849.00"),
        ("Oak coffee table", "furniture", 1, "329.00"),
        ("Upright piano", "musical", 1, "4800.00"),
        ("Floor lamp", "lighting", 2, "89.00"),
        ("Wool area rug, 8 x 10 ft", "decor", 1, "640.00"),
    ],
    "Kitchen": [
        ("French-door refrigerator", "appliance", 1, "2199.00"),
        ("Stand mixer", "kitchenware", 1, "449.00"),
        ("Cookware set, 12 pieces", "kitchenware", 1, "389.00"),
        ("Dining table with 6 chairs", "furniture", 1, "1450.00"),
    ],
    "Primary bedroom": [
        ("Queen mattress", "bedding", 1, "1199.00"),
        ("Solid wood queen bed frame", "furniture", 1, "899.00"),
        ("Gold wedding band and diamond necklace", "other", 1, "4200.00"),
        ("Grandmother's pearl earrings", "other", 1, "950.00"),
        ("Laptop computer", "electronics", 1, "1349.00"),
        ("Winter coats and work clothes", "clothing", 1, "2600.00"),
    ],
    "Kids' bedroom": [
        ("Bunk bed with mattresses", "furniture", 1, "1150.00"),
        ("Gaming console", "electronics", 1, "499.00"),
        ("Books and toys", "toys", 1, "900.00"),
        ("Desk and chair", "furniture", 2, "260.00"),
    ],
}


def seed_rivera_inventory(db: Session) -> None:
    home = db.scalar(select(Household).where(Household.name == "Rivera household"))
    if home is None or db.scalar(select(Item.id).where(Item.household_id == home.id).limit(1)):
        return
    scanned = now() - timedelta(days=60)
    for room_name, items in ROOMS.items():
        room = Room(household_id=home.id, name=room_name)
        db.add(room)
        db.flush()
        for name, category, qty, price in items:
            db.add(
                Item(
                    household_id=home.id,
                    room_id=room.id,
                    name=name,
                    category=category,
                    quantity=qty,
                    unit_price=Decimal(price),
                    price_source="user",
                    evidence_level=EvidenceLevel.PRE_DISASTER_SCAN,
                    confirmed=True,
                    created_at=scanned,
                )
            )
    db.flush()
    trust.refresh_level(db, home)  # a pre-disaster inventory is verification level 3
    db.commit()
