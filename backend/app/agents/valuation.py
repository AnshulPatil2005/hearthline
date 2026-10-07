"""Valuation agent: item description -> replacement price from Channel3.

The top search hit alone is unreliable (the spike priced a "tablet" as a replacement screen
and a stool at $1,120), so we take the cheapest in-stock new offer of each of several matching
products, drop replacement parts and accessories, and use the median. The low/high range is
kept so reviewers can see how sure the price is.
"""

import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache

from channel3_sdk import Channel3

from app.config import get_settings

CANDIDATES = 6
NOT_THE_ITEM = re.compile(
    r"\b(replacement|repair|spare|parts?|panel|lens|screen protector|cover only|slipcover|decal|sticker"
    r"|manual|cable|charger|remote control|knob|handle|hinge|filter)\b",
    re.IGNORECASE,
)


@dataclass
class Valuation:
    unit_price: Decimal
    price_low: Decimal
    price_high: Decimal
    product_id: str
    title: str
    url: str
    retailer: str
    offers_considered: int


@lru_cache
def channel3() -> Channel3:
    return Channel3(api_key=get_settings().channel3_api_key)


def _money(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cheapest_new_offer(offers):
    usable = [
        o for o in offers if o.price and o.price.price and o.availability == "InStock" and o.condition in (None, "new")
    ]
    return min(usable, key=lambda o: o.price.price) if usable else None


def best_offer(product):
    return cheapest_new_offer(product.offers or [])


def choose_price(products: list) -> Valuation | None:
    """Median of each relevant product's cheapest new offer; pick the product closest to it."""
    candidates = []
    for product in products:
        if NOT_THE_ITEM.search(product.title or ""):
            continue
        offer = best_offer(product)
        if offer is not None:
            candidates.append((offer.price.price, product, offer))
    if not candidates:
        return None
    prices = [c[0] for c in candidates]
    median = statistics.median(prices)
    price, product, offer = min(candidates, key=lambda c: abs(c[0] - median))
    return Valuation(
        unit_price=_money(median),
        price_low=_money(min(prices)),
        price_high=_money(max(prices)),
        product_id=product.id,
        title=product.title,
        url=offer.url,
        retailer=offer.domain,
        offers_considered=len(candidates),
    )


def value_item(search_query: str) -> Valuation | None:
    results = channel3().products.search(query=search_query, limit=CANDIDATES)
    return choose_price(list(results.items))


def value_items(search_queries: list[str]) -> list[Valuation | None]:
    """Price many items at once; Channel3 calls run in parallel."""
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(value_item, search_queries))
