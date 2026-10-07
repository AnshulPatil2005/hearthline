"""Demo scenario: the fictional Sablewood Fire in the fictional town of Sablewood, CA.

Idempotent: safe to run on every start-up. Run manually with `uv run python -m app.seed`.
Everything here is made up; no real disaster, place or person is depicted.
"""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import DisasterEvent, DisasterKind, Household, Role, User

FIRE_SLUG = "sablewood-fire"

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
    db.commit()


def main() -> None:
    with SessionLocal() as db:
        seed(db)
    print("Seeded the Sablewood demo scenario.")


if __name__ == "__main__":
    main()
