"""Command Center demo data: 2,000 fictional households across the Sablewood Fire, with their aid history.

Start-up only and idempotent (skips once the households exist). Generated from a fixed random seed, so
every deployment shows the same town. Damage is likelier near where the fire started, streets are
grouped by area, and every dollar of help is a real ledger entry, so the grid matches the books.
"""

import math
import random
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import geo, ledger
from app.models import (
    DisasterEvent,
    Household,
    LedgerAccount,
    LedgerPosting,
    LedgerTransaction,
    now,
)
from app.seed import FIRE_SLUG

COUNT = 2000
ORIGIN = (38.727, -120.655)  # (lat, lng) where the fire started, in the northwest of town
BOX = (38.668, 38.741, -120.671, -120.578)  # lat min/max, lng min/max: the burn area plus a margin

STREETS = [
    ["Lookout Rd", "Ridgecrest Rd", "Canyon View Rd", "Pine Hollow Dr", "Bear Creek Rd", "Sugar Pine Dr"],
    ["Juniper Lane", "Manzanita Way", "Black Oak Rd", "Madrone Ct", "Toyon Way", "Crestview Dr"],
    ["Cedar Ridge Rd", "Ponderosa Ave", "Old Mill Rd", "Quarry St", "Miners Ln", "Granite Bay Rd"],
    ["Sablewood Ave", "Foothill Blvd", "Hawthorn St", "Aspen Ct", "Fir St", "Deer Run"],
    ["Larch Court", "Willow Bend", "Elderberry Ln", "Buckeye Ct", "Redbud Ln", "Mesa Dr"],
]
FIRST = (
    "Maria Jose Wei Ana Luis Grace Samir Olivia Noah Mei Diego Fatima Ethan Priya Hana Carlos Linh Omar Rosa "
    "James Aiyana Tomas Leilani Darnell Sofia Minh Elena Kofi Ingrid Rafael Yusuf Chloe Arjun Lupe Dmitri"
).split()
LAST = (
    "Garcia Nguyen Smith Patel Johnson Lee Martinez Brown Kim Lopez Davis Chen Hernandez Wilson Tran Gonzalez "
    "Anderson Singh Thomas Ramirez Moore Pham Jackson Torres White Flores Harris Reyes Clark Yamamoto Lewis "
    "Begay Walker Cruz Hall Ali Young Santos King Okafor Wright Morales Scott Le Green Ortiz Baker Novak "
    "Adams Castillo Nelson Haddad Hill Mendoza Campbell Ito Mitchell Vargas Roberts Kowalski Carter Rossi"
).split()
LOSS = {
    "destroyed": (90_000, 320_000),
    "major": (35_000, 110_000),
    "minor": (6_000, 30_000),
    "affected": (800, 6_000),
}
NEEDS_BY_DAMAGE = {
    "destroyed": ["shelter", "clothing", "food"],
    "major": ["repairs", "shelter"],
    "minor": ["repairs", "cleanup"],
    "affected": ["cleanup", "water"],
}
OTHER_NEEDS = ["medical", "transport", "childcare", "pet_care", "mental_health", "food", "water"]

# Named households from the review and rebuild demos.
KNOWN = {
    "Rivera household": ("destroyed", 4, "185000", ["shelter", "clothing", "food", "childcare"]),
    "Haddad household": ("major", 3, "72000", ["repairs", "shelter"]),
    "Kowalski household": ("destroyed", 2, "140000", ["shelter", "mental_health"]),
}


def _damage(rng: random.Random, lat: float, lng: float, in_zone: bool) -> str:
    if not in_zone:
        return rng.choices(["affected", "minor"], [0.8, 0.2])[0]
    km = math.dist((lat * 111, lng * 87), (ORIGIN[0] * 111, ORIGIN[1] * 87))  # rough km at this latitude
    near = max(0.0, 1 - km / 7)  # 1 at the origin, 0 at 7 km
    weights = [0.1 + 0.6 * near, 0.15 + 0.2 * near, 0.35 - 0.2 * near, 0.4 - 0.35 * near]
    return rng.choices(["destroyed", "major", "minor", "affected"], weights)[0]


def _location(rng: random.Random, zone: dict, want_inside: bool) -> tuple[float, float, bool]:
    """Most households are inside the burn area; a few just outside it (they get level 0)."""
    while True:
        lat, lng = rng.uniform(BOX[0], BOX[1]), rng.uniform(BOX[2], BOX[3])
        if geo.in_zone(zone, lat, lng) == want_inside:
            return lat, lng, want_inside


def _street(lat: float, lng: float, rng: random.Random) -> str:
    row = min(4, int((BOX[1] - lat) / (BOX[1] - BOX[0]) * 5))
    col = min(5, int((lng - BOX[2]) / (BOX[3] - BOX[2]) * 6))
    return STREETS[max(row, 0)][max(col, 0)] if rng.random() < 0.85 else rng.choice(rng.choice(STREETS))


def _account(db: Session, cache: dict[str, LedgerAccount], code: str, household_id: int | None = None):
    if code not in cache:
        if household_id is not None:
            cache[code] = LedgerAccount(
                code=code, name=f"Funds held for household {household_id}", kind="liability", household_id=household_id
            )
            db.add(cache[code])
        else:
            cache[code] = ledger.account(db, code)
    return cache[code]


def _txn(kind: str, description: str, household_id: int | None, ref: str, when, lines) -> LedgerTransaction:
    txn = LedgerTransaction(
        kind=kind, description=description, household_id=household_id, paypal_ref=ref, meta={}, created_at=when
    )
    for acct, amount in lines:
        txn.postings.append(LedgerPosting(account=acct, amount=amount))
    return txn


def seed_command_center(db: Session) -> None:
    if db.scalar(select(func.count(Household.id))) >= COUNT:
        return
    fire = db.scalar(select(DisasterEvent).where(DisasterEvent.slug == FIRE_SLUG))
    rng = random.Random(2026)
    today = now()

    for name, (damage, size, loss, needs) in KNOWN.items():
        home = db.scalar(select(Household).where(Household.name == name))
        if home is not None:
            home.damage_level, home.household_size = damage, size
            home.estimated_loss, home.needs = Decimal(loss), needs

    homes = []
    for i in range(COUNT):
        lat, lng, inside = _location(rng, fire.zone, want_inside=rng.random() < 0.92)
        damage = _damage(rng, lat, lng, inside)
        first, last = rng.choice(FIRST), rng.choice(LAST)
        verified = inside and rng.random() < 0.55
        has_paypal = rng.random() < (0.9 if verified else 0.5 if inside else 0.3)
        low, high = LOSS[damage]
        needs = list(NEEDS_BY_DAMAGE[damage]) + rng.sample(OTHER_NEEDS, rng.choice([0, 0, 1, 1, 2]))
        homes.append(
            Household(
                name=f"{last} household",
                address_line=f"{rng.randint(10, 9899)} {_street(lat, lng, rng)}",
                city="Sablewood",
                state="CA",
                postal_code="95999",
                lat=round(lat, 6),
                lng=round(lng, 6),
                disaster_event=fire,
                residence_verified=verified,
                verification_level=2 if verified else 1 if inside else 0,
                payout_email=f"{first.lower()}.{last.lower()}{i}@personal.example.com" if has_paypal else None,
                damage_level=damage,
                household_size=rng.choices([1, 2, 3, 4, 5, 6], [0.2, 0.3, 0.18, 0.18, 0.09, 0.05])[0],
                estimated_loss=Decimal(rng.randrange(low, high, 50)),
                needs=list(dict.fromkeys(needs)),
                created_at=today - timedelta(days=rng.uniform(1, 28)),
            )
        )
    db.add_all(homes)
    db.flush()

    # The relief fund's money, and what has already reached families.
    accounts: dict[str, LedgerAccount] = {}
    cash, aid, grants = (_account(db, accounts, c) for c in (ledger.CASH, ledger.CASH_AID, ledger.GRANTS))
    grant = Decimal("2500000.00")
    txns = [
        _txn(
            "grant",
            "Sablewood Community Foundation grant (fictional)",
            None,
            "DEMO-GRANT-1",
            today - timedelta(days=22),
            [(cash, grant), (grants, -grant)],
        )
    ]
    wave = Decimal("500.00")
    for h in homes:
        if (
            h.verification_level >= 2
            and h.payout_email
            and h.damage_level in {"destroyed", "major"}
            and rng.random() < 0.6
        ):
            txns.append(
                _txn(
                    "payout",
                    f"Cash aid wave 1 for {h.name}",
                    h.id,
                    f"DEMO-WAVE1-{h.id}",
                    today - timedelta(days=16, hours=rng.uniform(0, 6)),
                    [(aid, wave), (cash, -wave)],
                )
            )
        if rng.random() < 0.2:
            amount = Decimal(rng.randrange(2_000, 25_000, 250))
            fund = _account(db, accounts, ledger.household_fund(h.id), h.id)
            txns.append(
                _txn(
                    "insurance_payment",
                    "Insurance advance (fictional insurer)",
                    h.id,
                    f"DEMO-INS-{h.id}",
                    today - timedelta(days=rng.uniform(2, 34)),
                    [(cash, amount), (fund, -amount)],
                )
            )
        if rng.random() < 0.1:
            amount = Decimal(rng.randrange(100, 1_500, 25))
            fund = _account(db, accounts, ledger.household_fund(h.id), h.id)
            txns.append(
                _txn(
                    "donation",
                    "Gift through the household's registry",
                    h.id,
                    f"DEMO-GIFT-{h.id}",
                    today - timedelta(days=rng.uniform(1, 40)),
                    [(cash, amount), (fund, -amount)],
                )
            )
    db.add_all(txns)
    db.commit()
