"""Shopper agent: finds real products for a funded need and picks the best one.

Channel3 supplies candidates (in stock, new, from approved retailers, no parts). The AI only
chooses among them and explains why; it never sets prices, payees or addresses.
"""

from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel

from app import ai
from app.agents.valuation import NOT_THE_ITEM, channel3, cheapest_new_offer

# Retailers Hearthline will buy from. In the sandbox they all map to one stand-in merchant account.
APPROVED_RETAILERS = {
    "amazon.com",
    "walmart.com",
    "target.com",
    "bestbuy.com",
    "homedepot.com",
    "lowes.com",
    "ikea.com",
    "wayfair.com",
    "costco.com",
    "macys.com",
    "kohls.com",
    "jcpenney.com",
    "llbean.com",
    "rei.com",
    "staples.com",
    "officedepot.com",
    "chewy.com",
    "petco.com",
    "petsmart.com",
    "dickssportinggoods.com",
    "bedbathandbeyond.com",
    "overstock.com",
    "zappos.com",
    "oldnavy.com",
    "gap.com",
    "crateandbarrel.com",
    "potterybarn.com",
    "westelm.com",
    "ashleyfurniture.com",
    "mattressfirm.com",
    "dell.com",
    "lenovo.com",
    "hp.com",
    "apple.com",
    "samsung.com",
    "bjs.com",
    "samsclub.com",
    "academy.com",
    "boscovs.com",
}

SYSTEM = """You buy replacement essentials for a family who lost their home in a disaster.
You get a need (what the family asked for, with their note) and numbered offers from real stores.
Pick the single offer that best matches the need: the right kind of item and size, new, sturdy,
and sensibly priced for a family starting over. Never pick accessories, parts or covers instead of
the item itself. If no offer genuinely fits, return choice = -1.
reasoning is 2-3 short sentences written for the family: name the product and store you picked and
why, and mention any notable alternative by store and product name. Never refer to offers by number.
confidence is 0-1: how sure you are this offer is what the family needs."""


@dataclass
class Candidate:
    product_id: str
    title: str
    retailer: str
    unit_price: Decimal
    url: str


class ShopperChoice(BaseModel):
    choice: int
    reasoning: str
    confidence: float


def find_candidates(query: str, max_unit_price: Decimal, limit: int = 8) -> list[Candidate]:
    results = channel3().products.search(query=query, limit=12)
    out: list[Candidate] = []
    for product in results.items:
        if NOT_THE_ITEM.search(product.title or ""):
            continue
        offer = cheapest_new_offer([o for o in (product.offers or []) if o.domain in APPROVED_RETAILERS])
        if offer is None or Decimal(str(offer.price.price)) > max_unit_price * 2:
            continue
        out.append(
            Candidate(
                product.id,
                product.title,
                offer.domain,
                Decimal(str(offer.price.price)).quantize(Decimal("0.01")),
                offer.url,
            )
        )
        if len(out) == limit:
            break
    return out


def choose(need: str, note: str, quantity: int, budget_per_unit: Decimal, candidates: list[Candidate]) -> ShopperChoice:
    listing = "\n".join(f"{i}. {c.title} | {c.retailer} | ${c.unit_price}" for i, c in enumerate(candidates))
    prompt = (
        f"Need: {need} (quantity {quantity})\nFamily's note: {note or '(none)'}\n"
        f"Budget per unit: about ${budget_per_unit}\n\nOffers:\n{listing}"
    )
    choice = ai.parse(ShopperChoice, system=SYSTEM, content=[ai.text_part(prompt)], max_tokens=1500)
    if not -1 <= choice.choice < len(candidates):
        choice.choice = -1
    choice.confidence = min(max(choice.confidence, 0.0), 1.0)
    return choice
