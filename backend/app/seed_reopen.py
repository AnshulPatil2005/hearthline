"""Reopen Fund demo data: three fictional Sablewood businesses. Start-up only and idempotent.

- Moreno's Bakery (persona Luis Moreno): verified, selling cards, the ovens already paid for.
- Pine Hollow Diner: waiting for staff to verify its license.
- Ridge Outfitters: its reopening date has passed, so the start-up deadline check refunds its buyers.
Card payments are recorded as DEMO captures, so start-up never calls PayPal.
"""

import random
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ledger, reopen
from app.models import Business, GiftCard, ReopenCampaign, ReopenTranche, Role, User, now

BUYERS = (
    "Ana Bea Carlos Dee Eli Fern Gus Hana Ivy Jon Kai Lena Mo Nia Omar Pia Quinn Rosa Sam Tia Uma Vic Wes Yara Zoe "
    "Amir Bo Cleo Dev Emi Finn Gia Hugo Iris Jude Kofi Lux Maya Nico Otto Priya Ravi Sky Theo Uri Vera Will Xan Yuki"
).split()


def _owner(db: Session, email: str, name: str) -> User:
    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, name=name, role=Role.BUSINESS, title="Business owner", is_demo=False)
        db.add(user)
        db.flush()
    return user


def _sell(db: Session, rng: random.Random, campaign: ReopenCampaign, target: Decimal, days: int) -> None:
    """Seeded card sales up to about `target`, recorded the way a real capture is (minus the PayPal call)."""
    sold = Decimal(0)
    while sold < target:
        amount = Decimal(rng.choice([25, 25, 50, 50, 50, 75, 100, 100, 150, 200]))
        card = GiftCard(
            campaign_id=campaign.id,
            code=reopen.new_code(campaign.business),
            buyer_name=rng.choice(BUYERS),
            amount_paid=amount,
            face_value=(amount * (100 + campaign.bonus_percent) / 100).quantize(Decimal("0.01")),
            payment_method=rng.choice(["paypal", "paypal", "venmo", "paylater"]),
            status="active",
            created_at=now() - timedelta(days=rng.uniform(1, days)),
        )
        card.balance, card.activated_at = card.face_value, card.created_at
        card.paypal_capture_id = f"DEMO-CARD-{campaign.id}-{len(campaign.cards) + 1}"
        campaign.cards.append(card)
        db.flush()
        fee = (amount * Decimal("0.0349") + Decimal("0.49")).quantize(Decimal("0.01"))
        txn = ledger.post(
            db,
            kind="gift_card",
            description=f"Gift card for {campaign.business.name}",
            paypal_ref=card.paypal_capture_id,
            meta={"gift_card_id": card.id, "campaign_id": campaign.id},
            lines={ledger.CASH: amount - fee, ledger.FEES: fee, reopen.escrow_account(campaign.id): -amount},
        )
        txn.created_at = card.created_at
        campaign.raised += amount
        sold += amount


def _release(db: Session, tranche: ReopenTranche, days_ago: int) -> None:
    tranche.status, tranche.released_at = "released", now() - timedelta(days=days_ago)
    tranche.paypal_ref = f"DEMO-TRANCHE-{tranche.id}"
    tranche.request_note = "Invoice from the oven supplier attached."
    txn = ledger.post(
        db,
        kind="tranche_payout",
        description=f"{tranche.campaign.business.name}: {tranche.title}",
        paypal_ref=tranche.paypal_ref,
        meta={"campaign_id": tranche.campaign_id, "tranche_id": tranche.id},
        lines={reopen.escrow_account(tranche.campaign_id): tranche.amount, ledger.CASH: -tranche.amount},
    )
    txn.created_at = tranche.released_at


def _campaign(db: Session, business: Business, bonus: int, reopen_in_days: int, steps) -> ReopenCampaign:
    today = now().replace(hour=9, minute=0, second=0, microsecond=0)
    campaign = ReopenCampaign(
        business_id=business.id,
        goal_amount=sum((Decimal(a) for _, a, _, _ in steps), Decimal(0)),
        bonus_percent=bonus,
        reopen_by=today + timedelta(days=reopen_in_days),
        created_at=today - timedelta(days=24),
    )
    for seq, (title, amount, start, length) in enumerate(steps, start=1):
        campaign.tranches.append(
            ReopenTranche(
                seq=seq,
                title=title,
                amount=Decimal(amount),
                start_date=today + timedelta(days=start),
                end_date=today + timedelta(days=start + length),
            )
        )
    business.campaigns.append(campaign)
    db.flush()
    return campaign


def seed_reopen_demo(db: Session) -> None:
    if db.scalar(select(Business.id).limit(1)) is not None:
        return
    rng = random.Random(11)
    luis = db.scalar(select(User).where(User.name == "Luis Moreno"))
    sam = db.scalar(select(User).where(User.name == "Sam Whitfield"))

    bakery = Business(
        owner_user_id=luis.id,
        name="Moreno's Bakery",
        slug="morenos-bakery",
        kind="bakery",
        address_line="120 Main St",
        city="Sablewood",
        state="CA",
        lat=38.704,
        lng=-120.632,
        license_number="SBW-BL-20417",
        payout_email="luis.moreno@business.example.com",
        verification="verified",
        verified_by_user_id=sam.id,
        verification_note="City license checked; the shop is inside the burn area.",
        story=(
            "We've baked bread on Main Street for 31 years. The fire took our ovens and the front of the shop, "
            "but not our sourdough starter. Buy a gift card now and spend it when we reopen; every card comes "
            "with a 20% thank-you bonus. You can see exactly what each dollar pays for below."
        ),
    )
    db.add(bakery)
    db.flush()
    campaign = _campaign(
        db,
        bakery,
        bonus=20,
        reopen_in_days=30,
        steps=[
            ("Replace the ovens", "7000", -20, 15),
            ("Restock flour, sugar and supplies", "3000", -4, 14),
            ("Repair the storefront and sign", "5000", 5, 20),
        ],
    )
    _sell(db, rng, campaign, Decimal("11200"), days=22)
    _release(db, campaign.tranches[0], days_ago=6)

    diner_owner = _owner(db, "ruth.abernathy@pinehollowdiner.example.com", "Ruth Abernathy")
    db.add(
        Business(
            owner_user_id=diner_owner.id,
            name="Pine Hollow Diner",
            slug="pine-hollow-diner",
            kind="restaurant",
            address_line="88 Pine Hollow Dr",
            city="Sablewood",
            state="CA",
            lat=38.712,
            lng=-120.648,
            license_number="SBW-BL-18832",
            payout_email="ruth.abernathy@business.example.com",
            story="Breakfast all day since 1984. Smoke damage closed our kitchen.",
        )
    )

    outfitter_owner = _owner(db, "jesse.ruiz@ridgeoutfitters.example.com", "Jesse Ruiz")
    outfitters = Business(
        owner_user_id=outfitter_owner.id,
        name="Ridge Outfitters",
        slug="ridge-outfitters",
        kind="retail",
        address_line="41 Lookout Rd",
        city="Sablewood",
        state="CA",
        lat=38.725,
        lng=-120.652,
        license_number="SBW-BL-11290",
        payout_email="jesse.ruiz@business.example.com",
        verification="verified",
        verified_by_user_id=sam.id,
        story="Camping and fishing gear. Our building is gone; we hoped to reopen in a temporary space.",
    )
    db.add(outfitters)
    db.flush()
    late = _campaign(
        db,
        outfitters,
        bonus=10,
        reopen_in_days=-2,  # the date has passed and the shop didn't reopen
        steps=[("Lease a temporary space", "1000", -20, 10), ("Restock gear", "3000", -10, 10)],
    )
    _sell(db, rng, late, Decimal("2400"), days=20)
    _release(db, late.tranches[0], days_ago=12)
    db.commit()
