"""Trust layer: verification levels and Sentinel's warning signs.

Nothing here decides anything. Levels unlock what a household can receive; flags route a case
to deeper human review. A real victim who lost their documents can always reach level 2
through a caseworker's vouch.
"""

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import imagehash
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import geo
from app.models import EvidenceLevel, Household, Item, Media

DUPLICATE_DISTANCE = 6  # max differing bits (of 64) for two photos to count as the same picture
SEVERITY_POINTS = {"high": 40, "medium": 15, "low": 5}
LEVEL_NAMES = {0: "unverified", 1: "in_zone", 2: "residence_confirmed", 3: "pre_disaster_inventory"}


@dataclass
class Flag:
    code: str
    severity: str  # low | medium | high
    message: str
    evidence: dict


def _aware(dt: datetime | None) -> datetime | None:
    return dt if dt is None or dt.tzinfo else dt.replace(tzinfo=UTC)


def in_disaster_zone(home: Household) -> bool:
    return bool(
        home.disaster_event and home.lat is not None and geo.in_zone(home.disaster_event.zone, home.lat, home.lng)
    )


def verification_level(db: Session, home: Household) -> int:
    """0 unverified · 1 address inside the disaster zone · 2 residence confirmed (document or a
    caseworker's vouch) · 3 plus an inventory scanned before the disaster."""
    if not in_disaster_zone(home):
        return 0
    if not (home.residence_verified or home.vouched_by_user_id):
        return 1
    has_pre_disaster_scan = db.scalar(
        select(func.count(Item.id)).where(
            Item.household_id == home.id, Item.evidence_level == EvidenceLevel.PRE_DISASTER_SCAN
        )
    )
    return 3 if has_pre_disaster_scan else 2


def refresh_level(db: Session, home: Household) -> int:
    home.verification_level = verification_level(db, home)
    return home.verification_level


def duplicate_photos(db: Session, home: Household) -> list[tuple[Media, Media, int]]:
    """Photos in this household that closely match a photo from another household."""
    mine = list(db.scalars(select(Media).where(Media.household_id == home.id, Media.phash.is_not(None))))
    if not mine:
        return []
    others = list(db.scalars(select(Media).where(Media.household_id != home.id, Media.phash.is_not(None))))
    matches = []
    for m in mine:
        h = imagehash.hex_to_hash(m.phash)
        for o in others:
            distance = int(h - imagehash.hex_to_hash(o.phash))  # numpy int -> plain int for JSON
            if distance <= DUPLICATE_DISTANCE:
                matches.append((m, o, distance))
                break
    return matches


def sentinel_flags(db: Session, home: Household, claim_amount: Decimal = Decimal(0)) -> list[Flag]:
    flags: list[Flag] = []

    if not in_disaster_zone(home):
        flags.append(
            Flag(
                "outside_zone",
                "high",
                "The home address is not inside any active disaster area.",
                {"lat": home.lat, "lng": home.lng},
            )
        )

    # Whoever uploaded a matching photo *later* is the likely copier. The original owner only gets a
    # low-severity notice, so a family whose pictures were stolen isn't treated as a suspect.
    copied, original = [], []
    for mine, other, distance in duplicate_photos(db, home):
        match = {"media_id": mine.id, "other_household_id": other.household_id, "distance": distance}
        (copied if _aware(mine.uploaded_at) >= _aware(other.uploaded_at) else original).append(match)
    if copied:
        flags.append(
            Flag(
                "duplicate_photo",
                "high",
                f"{len(copied)} photo(s) match photos another household uploaded earlier.",
                {"matches": copied},
            )
        )
    if original:
        flags.append(
            Flag(
                "photo_copied_by_other",
                "low",
                f"{len(original)} of this household's photos were later uploaded by someone else. "
                "They may be the target of an impersonation scam.",
                {"matches": original},
            )
        )

    if home.payout_email:
        sharing = list(
            db.scalars(select(Household.id).where(Household.payout_email == home.payout_email, Household.id != home.id))
        )
        if sharing:
            flags.append(
                Flag(
                    "shared_payout_account",
                    "high",
                    f"The PayPal account for cash aid is also used by {len(sharing)} other household(s).",
                    {"other_household_ids": sharing},
                )
            )

    event = home.disaster_event
    if event is not None:
        photos = list(db.scalars(select(Media).where(Media.household_id == home.id, Media.kind == "photo")))
        declared = _aware(event.declared_at)
        after = [m for m in photos if m.captured_at and _aware(m.captured_at) > declared]
        if after:
            flags.append(
                Flag(
                    "photo_after_disaster",
                    "medium",
                    f"{len(after)} photo(s) of belongings were taken after the disaster began.",
                    {"media_ids": [m.id for m in after]},
                )
            )
        if len(photos) >= 3 and sum(m.captured_at is None for m in photos) / len(photos) > 0.8:
            flags.append(
                Flag(
                    "no_photo_metadata",
                    "low",
                    "Most photos have no capture date (often screenshots or downloaded images).",
                    {"photos": len(photos)},
                )
            )

    items = list(db.scalars(select(Item).where(Item.household_id == home.id)))
    outliers = [i for i in items if i.unit_price and i.price_high and i.unit_price > i.price_high * 2]
    if outliers:
        flags.append(
            Flag(
                "price_outlier",
                "medium",
                f"{len(outliers)} item(s) are priced at more than twice the highest market price found.",
                {"item_ids": [i.id for i in outliers]},
            )
        )
    memory_big = [i for i in items if i.evidence_level == EvidenceLevel.MEMORY and (i.total_value or 0) > 1000]
    if memory_big:
        flags.append(
            Flag(
                "high_value_no_evidence",
                "medium",
                f"{len(memory_big)} item(s) worth over $1,000 each have no photo or receipt.",
                {"item_ids": [i.id for i in memory_big]},
            )
        )

    newest_member = min((_aware(u.created_at) for u in home.members), default=None)
    if newest_member and datetime.now(UTC) - newest_member < timedelta(days=1) and claim_amount > 5000:
        flags.append(
            Flag(
                "new_account_large_claim",
                "low",
                "A large claim from an account created today.",
                {"claim": str(claim_amount)},
            )
        )
    return flags


def risk(flags: list[Flag]) -> tuple[int, str]:
    """Any single high-severity sign makes the case high risk (two independent reviewers)."""
    score = min(100, sum(SEVERITY_POINTS[f.severity] for f in flags))
    if score >= 50 or any(f.severity == "high" for f in flags):
        return score, "high"
    return score, "medium" if score >= 15 else "low"


def flags_json(flags: list[Flag]) -> list[dict]:
    return [asdict(f) for f in flags]
