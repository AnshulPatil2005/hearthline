"""Price Watch demo data: a fictional local price survey around Sablewood. Start-up only and idempotent.

Online products get real Channel3 price history when the Shopper looks at them. These local sellers are
made up, so the report has something to show from day one; the page labels them as demo data.
"""

import random
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import gouging
from app.models import DisasterEvent, PriceSnapshot, PriceWatch, now
from app.seed import FIRE_SLUG

# (title, seller, category, price before the fire, price after it as a multiple)
SURVEY = [
    ("Bottled water, 24 x 16.9 oz", "Pine Hollow Market", "water", "5.99", 2.5),
    ("Bottled water, 24 x 16.9 oz", "Sablewood Supply Co.", "water", "6.49", 1.05),
    ("Portable generator, 4,500 W", "Sablewood Supply Co.", "generator", "699.00", 1.86),
    ("Portable generator, 4,500 W", "Foothill Hardware", "generator", "729.00", 1.0),
    ("Heavy-duty tarp, 20 x 30 ft", "Foothill Hardware", "building_materials", "54.99", 1.08),
    ("Heavy-duty tarp, 20 x 30 ft", "Ridge Gas & Go", "building_materials", "49.99", 2.2),
    ("Plywood sheet, 1/2 in. 4 x 8 ft", "Foothill Hardware", "building_materials", "38.50", 1.06),
    ("N95 masks, box of 20", "Pine Hollow Market", "medical", "19.99", 3.0),
    ("N95 masks, box of 20", "Sablewood Pharmacy", "medical", "21.49", 1.0),
    ("Gas can, 5 gal", "Ridge Gas & Go", "fuel", "24.99", 1.6),
    ("Regular gasoline, per gallon", "Ridge Gas & Go", "fuel", "4.89", 1.09),
    ("Propane tank exchange", "Sablewood Supply Co.", "fuel", "24.99", 1.0),
    ("AA batteries, 24 pack", "Pine Hollow Market", "emergency_supplies", "17.99", 1.35),
    ("First aid kit, 200 pieces", "Sablewood Pharmacy", "medical", "29.99", 1.03),
    ("Chainsaw, 18 in. gas", "Foothill Hardware", "tools", "299.00", 1.1),
    ("Motel room, one night", "Lookout Motor Lodge", "lodging", "129.00", 2.24),
    ("Motel room, one night", "Sablewood Inn", "lodging", "142.00", 1.07),
]


def seed_price_watch(db: Session) -> None:
    fire = db.scalar(select(DisasterEvent).where(DisasterEvent.slug == FIRE_SLUG))
    if fire is None or db.scalar(select(PriceWatch.id).limit(1)) is not None:
        return
    rng = random.Random(396)
    declared = gouging._aware(fire.declared_at).date()
    today = now().date()
    for title, seller, category, before, factor in SURVEY:
        base = Decimal(before)
        watch = PriceWatch(
            disaster_event_id=fire.id, title=title, seller=seller, category=category, source="local_survey"
        )
        jump = declared + timedelta(days=rng.randint(0, 3))  # gougers raise prices within days
        day = declared - timedelta(days=gouging.BASELINE_DAYS + 5)
        while day <= today:
            price = base * Decimal(str(factor)) if day >= jump else base
            if rng.random() < 0.15:  # the odd sale or price tweak
                price *= Decimal(str(rng.choice([0.9, 0.95, 1.03])))
            watch.snapshots.append(PriceSnapshot(observed_on=day, price=price.quantize(Decimal("0.01"))))
            day += timedelta(days=rng.choice([1, 1, 2, 3]))  # surveys aren't daily
        db.add(watch)
        db.flush()
        gouging.rejudge(watch, fire)
    db.commit()
