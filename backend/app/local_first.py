"""Local first: aid money spent at the town's own businesses helps the town recover twice.

Before buying from a web store, the Shopper looks at what verified local businesses that are open again sell in the
family's town. The AI judges whether a local offer fits the need and which online offer it would otherwise buy; code
decides: buy locally when the fit is good and the price is at most 15% above that online offer. The usual spending
rules still apply.
"""

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.shopper import Candidate
from app.models import Business, Household, LocalOffer, RegistryItem

PRICE_MARGIN = Decimal("1.15")  # a local offer may cost up to 15% more than the best online one
MIN_FIT = 0.6  # the AI's confidence that a local offer is what the family needs


@dataclass
class LocalPick:
    candidate: Candidate
    business: Business
    online_best: Candidate | None  # the online offer the Shopper would otherwise have bought


def open_now(business: Business) -> bool:
    """Verified, and either it never closed or its Reopen Fund says it reopened."""
    if business.verification != "verified":
        return False
    latest = business.campaigns[-1] if business.campaigns else None
    return latest is None or latest.status == "reopened"


def candidates(
    db: Session, item: RegistryItem, home: Household, budget_per_unit: Decimal
) -> dict[str, tuple[Candidate, Business]]:
    """In-stock offers in the item's category from open local businesses in the family's town, keyed by id."""
    found: dict[str, tuple[Candidate, Business]] = {}
    offers = db.scalars(
        select(LocalOffer)
        .join(Business)
        .where(LocalOffer.available, LocalOffer.category == item.category, Business.city == home.city)
        .order_by(LocalOffer.unit_price)
    )
    for offer in offers:
        if offer.unit_price > budget_per_unit * 2 or not open_now(offer.business):
            continue
        key = f"local-{offer.id}"
        found[key] = (
            Candidate(key, offer.title, offer.business.name, offer.unit_price, f"/reopen/{offer.business.slug}"),
            offer.business,
        )
    return found


def prefer_local(local: Candidate, online_pick: Candidate | None) -> bool:
    """Code's rule: local wins when it costs at most PRICE_MARGIN times the online offer the Shopper would otherwise
    buy (the AI's best fit online, not merely the cheapest listing), or when nothing online fits."""
    return online_pick is None or local.unit_price <= online_pick.unit_price * PRICE_MARGIN


def note(pick: LocalPick) -> str:
    """Why the Shopper bought locally, in the family's words."""
    if pick.online_best is None:
        return f"{pick.business.name} is a verified local business open again after the fire."
    more = (pick.candidate.unit_price / pick.online_best.unit_price - 1) * 100
    if more <= 0:
        compare = f"no more than the best online match (${pick.online_best.unit_price} at {pick.online_best.retailer})"
    else:
        compare = f"{more:.0f}% more than {pick.online_best.retailer} (${pick.online_best.unit_price}), within 15%"
    return f"Bought locally: {pick.business.name} is open again after the fire; its price is {compare}."
