"""Demo scenario: the fictional Sablewood Fire in the fictional town of Sablewood, CA.

Idempotent: safe to run on every start-up. Run manually with `uv run python -m app.seed`.
Everything here is made up; no real disaster, place or person is depicted.
"""

import io
import random
from datetime import timedelta
from decimal import Decimal

from PIL import Image, ImageDraw
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, ledger, rebuild, review
from app.db import SessionLocal
from app.media import prepare_image
from app.models import (
    Case,
    Contractor,
    DisasterEvent,
    DisasterKind,
    Donation,
    EvidenceLevel,
    Household,
    Item,
    Media,
    RebuildProject,
    Registry,
    RegistryItem,
    Role,
    User,
    now,
)

FIRE_SLUG = "sablewood-fire"
FIRE_DAYS_AGO = 26  # the demo is set about four weeks after the fire

# Burn area as a GeoJSON polygon ([lng, lat] pairs), roughly 7 km across.
SABLEWOOD_FIRE_ZONE = {
    "type": "Polygon",
    "coordinates": [
        [
            [-120.668, 38.712],
            [-120.651, 38.731],
            [-120.622, 38.738],
            [-120.594, 38.727],
            [-120.581, 38.705],
            [-120.590, 38.683],
            [-120.613, 38.671],
            [-120.641, 38.674],
            [-120.662, 38.690],
            [-120.668, 38.712],
        ]
    ],
}

HOUSEHOLDS = [
    {
        "key": "rivera",
        "name": "Rivera household",
        "address_line": "214 Juniper Lane",
        "city": "Sablewood",
        "state": "CA",
        "postal_code": "95999",
        "lat": 38.709,
        "lng": -120.627,
        "insured_contents_value": Decimal("80000.00"),
    },
]

PERSONAS = [
    (
        "elena.rivera@demo.hearthline.app",
        "Elena Rivera",
        Role.HOUSEHOLD,
        "rivera",
        "Household · her family's home burned in the Sablewood Fire",
    ),
    (
        "marcus.chen@demo.hearthline.app",
        "Marcus Chen",
        Role.DONOR,
        None,
        "Donor · wants to fund specific things families need",
    ),
    (
        "dana.okafor@demo.hearthline.app",
        "Dana Okafor",
        Role.CONTRACTOR,
        None,
        "Contractor · Okafor Builders, licensed general contractor",
    ),
    ("priya.nair@demo.hearthline.app", "Priya Nair", Role.REVIEWER, None, "Claim reviewer · Sablewood Relief Network"),
    (
        "tom.becker@demo.hearthline.app",
        "Tom Becker",
        Role.REVIEWER,
        None,
        "Claim reviewer · Sablewood Relief Network (second reviewer)",
    ),
    (
        "grace.alvarez@demo.hearthline.app",
        "Grace Alvarez",
        Role.SUPERVISOR,
        None,
        "Review supervisor · settles disagreements between reviewers",
    ),
    (
        "sam.whitfield@demo.hearthline.app",
        "Sam Whitfield",
        Role.ORG_ADMIN,
        None,
        "Relief organization admin · runs the Command Center",
    ),
    (
        "luis.moreno@demo.hearthline.app",
        "Luis Moreno",
        Role.BUSINESS,
        None,
        "Business owner · Moreno's Bakery, closed by the fire",
    ),
    (
        "rosa.delgado@demo.hearthline.app",
        "Rosa Delgado",
        Role.BUSINESS,
        None,
        "Business owner · Sablewood Mercantile, open again after the fire",
    ),
]


RIVERA_REGISTRY = {
    "slug": "rivera-family",
    "title": "Help the Riveras come home",
    "story": (
        "Our house on Juniper Lane burned in the Sablewood Fire. We got out with our kids, Maya (12) and Leo (8), "
        "and our dog Pepper, but almost nothing else. Instead of cash, we've listed the specific things we need "
        "first. Every item is bought by Hearthline and shipped to our temporary address, and you can see where "
        "every dollar goes. Thank you for helping us start again."
    ),
}

# (name, note, category, quantity, unit price, priority)
RIVERA_ITEMS = [
    ("Twin mattresses", "For Maya and Leo. They're sleeping on an air mattress.", "bedding", 2, "249.00", 10),
    ("Twin bed frames", "Simple metal frames are fine.", "furniture", 2, "129.00", 20),
    ("School laptop for Maya", "Her school assigns homework online.", "electronics", 1, "449.00", 30),
    ("Winter jackets for the kids", "Sizes 12 and 8.", "clothing", 2, "79.00", 40),
    ("Kitchen starter set", "Pots, pans, plates and utensils for the rental.", "kitchenware", 1, "189.00", 50),
    ("Steel-toe work boots", "Elena's were lost; she needs them for work.", "clothing", 1, "139.00", 60),
    ("Dog crate and bed for Pepper", "The rental requires a crate.", "other", 1, "95.00", 70),
]


def _get_or_create(db: Session, model, lookup: dict, **values):
    row = db.scalar(select(model).filter_by(**lookup))
    if row is None:
        row = model(**lookup, **values)
        db.add(row)
        db.flush()
    return row


def seed(db: Session) -> None:
    fire = _get_or_create(
        db,
        DisasterEvent,
        {"slug": FIRE_SLUG},
        name="Sablewood Fire",
        kind=DisasterKind.WILDFIRE,
        zone=SABLEWOOD_FIRE_ZONE,
        is_fictional=True,
        declared_at=now() - timedelta(days=FIRE_DAYS_AGO),
        # The county extended the state's 30-day price protection for six months (fictional).
        price_protection_until=now() + timedelta(days=180 - FIRE_DAYS_AGO),
    )
    homes = {}
    for spec in HOUSEHOLDS:
        values = {k: v for k, v in spec.items() if k not in {"key", "name"}}
        homes[spec["key"]] = _get_or_create(db, Household, {"name": spec["name"]}, disaster_event=fire, **values)
    for email, name, role, home_key, title in PERSONAS:
        _get_or_create(
            db,
            User,
            {"email": email},
            name=name,
            role=role,
            title=title,
            is_demo=True,
            household=homes.get(home_key),
        )
    dana = db.scalar(select(User).where(User.email == "dana.okafor@demo.hearthline.app"))
    _get_or_create(
        db,
        Contractor,
        {"user_id": dana.id},
        business_name="Okafor Builders",
        license_number="1048821",
        license_state="CA",
        license_verified=True,
        payout_email="dana.okafor@business.example.com",
    )
    rivera = homes["rivera"]
    if db.scalar(select(Registry).where(Registry.slug == RIVERA_REGISTRY["slug"])) is None:
        registry = Registry(household_id=rivera.id, **RIVERA_REGISTRY)
        for name, note, category, qty, price, priority in RIVERA_ITEMS:
            registry.items.append(
                RegistryItem(
                    name=name, note=note, category=category, quantity=qty, unit_price=Decimal(price), priority=priority
                )
            )
        db.add(registry)
    db.commit()


# --- Review demo: a small Sablewood caseload, including one impersonation scam ------------------

SCAM_SENTINEL = (
    "The claim has multiple high-severity warnings, including an address outside the active disaster area, "
    "photos copied from another family, and a PayPal account shared with another applicant. These issues need "
    "direct follow-up before any funds can be distributed.",
    [
        "Could you confirm your current home address and how it was affected by the fire?",
        "Can you provide your own original photos of the damage to your property?",
        "Why is this PayPal account also used by another household?",
    ],
)


def _room_picture(seed: int) -> bytes:
    """A simple generated 'room' picture (placeholder until real demo photos are added)."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (640, 480), (rnd.randint(200, 240), rnd.randint(190, 230), rnd.randint(170, 210)))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 340, 640, 480], fill=(120 + seed % 40, 90, 70))  # floor
    d.rectangle([60, 220, 330, 360], fill=(90, 100, 120))  # sofa
    d.rectangle([380, 120, 560, 260], fill=(30, 30, 35))  # TV
    d.rectangle([400, 260, 540, 350], fill=(140, 100, 60))  # stand
    d.ellipse([470 - seed * 7 % 60, 40, 520 - seed * 7 % 60, 90], fill=(250, 240, 200))  # lamp
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _add_photo(db: Session, home: Household, raw: bytes, days_ago: int) -> None:
    img = prepare_image(raw)
    db.add(
        Media(
            household_id=home.id,
            content_type="image/jpeg",
            data=img.jpeg,
            width=img.width,
            height=img.height,
            sha256=img.sha256,
            phash=img.phash,
            uploaded_at=now() - timedelta(days=days_ago),
        )
    )


def _household(db: Session, fire: DisasterEvent | None, **values) -> Household:
    home = db.scalar(select(Household).where(Household.name == values["name"]))
    if home is None:
        home = Household(
            disaster_event=fire,
            city=values.pop("city", "Sablewood"),
            state=values.pop("state", "CA"),
            postal_code=values.pop("postal_code", "95999"),
            **values,
        )
        db.add(home)
        db.flush()
    return home


def seed_review_demo(db: Session) -> None:
    if db.scalar(select(Case.id).limit(1)) is not None:
        return
    fire = db.scalar(select(DisasterEvent).where(DisasterEvent.slug == FIRE_SLUG))
    rng = random.Random(7)

    rivera = db.scalar(select(Household).where(Household.name == "Rivera household"))
    for member in rivera.members:  # the Riveras signed up months before the fire (see their early scans)
        member.created_at = now() - timedelta(days=90)
    rivera.payout_email = "elena.rivera@personal.example.com"
    rivera.residence_verified = True  # utility bill checked at the shelter (level 2: can receive cash aid)
    for n in (1, 2):
        _add_photo(db, rivera, _room_picture(n), days_ago=60)  # scanned well before the fire

    haddad = _household(
        db,
        fire,
        name="Haddad household",
        address_line="38 Cedar Ridge Rd",
        lat=38.700,
        lng=-120.640,
        payout_email="sami.haddad@personal.example.com",
        residence_verified=True,
    )
    kowalski = _household(
        db,
        fire,
        name="Kowalski household",
        address_line="5 Larch Court",
        lat=38.716,
        lng=-120.601,
        payout_email="anna.kowalski@personal.example.com",
    )
    for name, price in (("Grand piano", "8000"), ("Jewelry collection", "3500")):
        db.add(
            Item(household_id=kowalski.id, name=name, unit_price=Decimal(price), evidence_level=EvidenceLevel.MEMORY)
        )

    scam = _household(
        db,
        None,
        name="Rivera family fund",
        address_line="1180 Desert Bloom Ct",
        city="Henderson",
        state="NV",
        postal_code="89002",
        lat=36.04,
        lng=-114.98,
        payout_email="help.riveras@personal.example.com",
    )
    _household(
        db,
        None,
        name="M. Grey household",
        address_line="77 Dune Way",
        city="Henderson",
        state="NV",
        postal_code="89002",
        lat=36.05,
        lng=-114.97,
        payout_email="help.riveras@personal.example.com",
    )
    for n in (1, 2):
        _add_photo(db, scam, _room_picture(n), days_ago=1)  # the Riveras' photos, re-uploaded
    reg = Registry(
        household_id=scam.id,
        slug="riveras-rebuild-fund",
        title="Help the Rivera family rebuild",
        story="Our home burned in the Sablewood Fire. Anything helps.",
        status="active",
    )
    reg.items.append(RegistryItem(name="Laptop for school", unit_price=Decimal("450"), funded_amount=Decimal("125")))
    db.add(reg)
    db.flush()
    for n, (donor, amount) in enumerate((("Jordan", "75"), (None, "50")), start=1):
        db.add(
            Donation(
                registry_id=reg.id,
                registry_item_id=reg.items[0].id,
                donor_name=donor,
                amount=Decimal(amount),
                status="captured",
                paypal_capture_id=f"DEMO-SCAM-{n}",
                paypal_order_id=f"DEMO-ORDER-{n}",
                captured_at=now(),
            )
        )
        ledger.record_donation(
            db,
            household_id=scam.id,
            gross=Decimal(amount),
            fee=Decimal("0"),
            capture_id=f"DEMO-SCAM-{n}",
            description="Donation (demo data)",
            meta={},
        )
    db.commit()

    review.open_case(
        db,
        rivera,
        kind="cash_aid",
        title="Cash aid request",
        amount=Decimal("800"),
        note="Motel and groceries while we find a rental.",
        rng=rng,
        explain=False,
    )
    review.open_case(
        db,
        haddad,
        kind="cash_aid",
        title="Cash aid request",
        amount=Decimal("1500"),
        note="Deposit on a rental for our family of five.",
        rng=rng,
        explain=False,
    )
    review.open_case(
        db,
        kowalski,
        kind="contents_claim",
        title="Contents claim review",
        amount=Decimal("11500"),
        note="Our piano and my mother's jewelry were lost. No photos survived.",
        rng=rng,
        explain=False,
    )
    scam_case = review.open_case(
        db, scam, kind="registry_verification", title="Registry: Help the Rivera family rebuild", rng=rng, explain=False
    )
    scam_case.sentinel_summary, scam_case.sentinel_questions = SCAM_SENTINEL
    scam_case.sentinel_recommendation = "escalate"
    db.commit()


# (title, what "done" looks like, amount, is deposit, start offset in days from today, length in days)
RIVERA_REBUILD = [
    ("Deposit", "Contract signed and permits filed.", "1000.00", True, -24, 3),
    (
        "Debris removal and demolition",
        "Burned structure and ash hauled away, lot cleared down to the slab, debris dumpster removed.",
        "6000.00",
        False,
        -18,
        16,
    ),
    (
        "Foundation repair",
        "Cracked slab sections replaced; new anchor bolts set and inspected.",
        "9000.00",
        False,
        1,
        14,
    ),
    ("Framing", "Walls, roof trusses and sheathing up; framing inspection passed.", "12000.00", False, 16, 21),
    ("Roofing", "Class A fire-rated roof installed with ember-resistant vents.", "9500.00", False, 38, 10),
    (
        "Electrical and plumbing rough-in",
        "Wiring, panel and supply lines installed and passed rough-in inspection.",
        "10500.00",
        False,
        49,
        14,
    ),
]


def _cleared_lot_picture() -> bytes:
    """A generated 'cleared lot' site photo (placeholder until real demo photos are added)."""
    img = Image.new("RGB", (800, 600), (178, 205, 228))  # sky
    d = ImageDraw.Draw(img)
    d.rectangle([0, 300, 800, 600], fill=(150, 120, 90))  # bare dirt
    d.rectangle([180, 360, 620, 470], fill=(170, 170, 165))  # cleaned slab
    d.rectangle([660, 330, 780, 400], fill=(40, 90, 60))  # dumpster
    d.line([(0, 300), (800, 300)], fill=(90, 110, 80), width=6)  # tree line
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def seed_rebuild_demo(db: Session) -> None:
    """Rivera's rebuild with Okafor Builders: deposit paid, demolition submitted and waiting for Elena."""
    if db.scalar(select(RebuildProject.id).limit(1)) is not None:
        return
    rivera = db.scalar(select(Household).where(Household.name == "Rivera household"))
    elena = db.scalar(select(User).where(User.name == "Elena Rivera"))
    dana = db.scalar(select(User).where(User.name == "Dana Okafor"))
    contractor = db.scalar(select(Contractor).where(Contractor.user_id == dana.id))

    ledger.post(
        db,
        kind="insurance_payment",
        description="Dwelling coverage advance (Golden Poppy Mutual, fictional)",
        household_id=rivera.id,
        paypal_ref="DEMO-INSURANCE-ADVANCE-1",
        meta={"insurer": "Golden Poppy Mutual"},
        lines={ledger.CASH: Decimal("60000.00"), ledger.household_fund(rivera.id): -Decimal("60000.00")},
    )
    project = RebuildProject(household_id=rivera.id, contractor_id=contractor.id, title="Rebuild 214 Juniper Lane")
    db.add(project)
    db.flush()
    today = now().replace(hour=8, minute=0, second=0, microsecond=0)
    plan = [
        {
            "title": title,
            "done_looks_like": done,
            "amount": Decimal(amount),
            "is_deposit": deposit,
            "start_date": today + timedelta(days=start),
            "end_date": today + timedelta(days=start + length),
        }
        for title, done, amount, deposit, start, length in RIVERA_REBUILD
    ]
    rebuild.submit_plan(db, project, plan, dana)
    rebuild.accept_plan(db, project, elena)

    deposit, demolition = project.milestones[0], project.milestones[1]
    # Recorded directly so start-up never sends a real payout; the live flow goes through rebuild.pay_milestone.
    ledger.post(
        db,
        kind="milestone_payment",
        description=f"{contractor.business_name}: {deposit.title}",
        household_id=rivera.id,
        paypal_ref="DEMO-MILESTONE-DEPOSIT",
        meta={"project_id": project.id, "milestone_id": deposit.id},
        lines={rebuild.escrow_account(project.id): deposit.amount, ledger.CASH: -deposit.amount},
    )
    deposit.status, deposit.paid_at, deposit.paypal_ref = "paid", today - timedelta(days=23), "DEMO-MILESTONE-DEPOSIT"
    deposit.submitted_at = today - timedelta(days=24)
    deposit.site_check = {
        "verdict": "matches",
        "confidence": 1.0,
        "observations": ["Deposit: no work to photograph"],
        "concerns": [],
        "metadata_concerns": [],
    }

    img = prepare_image(_cleared_lot_picture())
    photo = Media(
        household_id=rivera.id,
        content_type="image/jpeg",
        data=img.jpeg,
        width=img.width,
        height=img.height,
        sha256=img.sha256,
        phash=img.phash,
        captured_at=today - timedelta(days=1),
        kind="site_photo",
    )
    db.add(photo)
    db.flush()
    demolition.photo_media_ids = [photo.id]
    demolition.status, demolition.submitted_at = "submitted", today - timedelta(hours=20)
    demolition.site_check = {
        "verdict": "matches",
        "confidence": 0.86,
        "observations": [
            "The lot is cleared down to a bare concrete slab",
            "No ash or burned debris is visible",
            "A roll-off dumpster is still on site at the right edge",
        ],
        "concerns": ["Ask when the dumpster will be picked up"],
        "metadata_concerns": [],
    }
    audit.record(
        db,
        actor_user_id=dana.id,
        action="milestone.submitted",
        subject_type="milestone",
        subject_id=demolition.id,
        data={"verdict": "matches", "confidence": 0.86},
    )
    # A second family has invited Okafor Builders and is waiting for a plan.
    haddad = db.scalar(select(Household).where(Household.name == "Haddad household"))
    if haddad is not None:
        db.add(
            RebuildProject(
                household_id=haddad.id, contractor_id=contractor.id, title="Repair the fire-damaged garage and roof"
            )
        )
    db.commit()


def main() -> None:
    with SessionLocal() as db:
        seed(db)
        seed_review_demo(db)
        from app.seed_inventory import seed_rivera_inventory

        seed_rivera_inventory(db)
        seed_rebuild_demo(db)
        from app.seed_command import seed_command_center, seed_crews, seed_prepared  # this module's constants

        seed_command_center(db)
        seed_prepared(db)
        seed_crews(db)
        from app import reopen
        from app.seed_reopen import seed_reopen_demo

        seed_reopen_demo(db)
        from app.seed_local import seed_hardware_store, seed_local_store

        seed_local_store(db)
        seed_hardware_store(db)
        reopen.run_deadlines(db)  # Render's free plan has no cron: check Reopen deadlines at every start
        from app.seed_prices import seed_price_watch

        seed_price_watch(db)
        from app.seed_giving import seed_giving_demo

        seed_giving_demo(db)
        from app.seed_disputes import seed_disputes_demo

        seed_disputes_demo(db)
        from app.models import AuditEvent

        # The books open here: reconciliation with PayPal starts from this database's first seed (a demo reset
        # wipes the audit log, so it opens them again). Render reruns the seed at every start; record it once.
        if db.scalar(select(AuditEvent.id).where(AuditEvent.action == "demo.seeded").limit(1)) is None:
            audit.record(db, action="demo.seeded", subject_type="demo", subject_id="sablewood")
            db.commit()
    print("Seeded the Sablewood demo scenario.")


if __name__ == "__main__":
    main()
