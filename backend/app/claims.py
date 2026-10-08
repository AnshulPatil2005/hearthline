"""What a policy means for this family's claim: plain arithmetic over what the Policy agent read.

The AI only reads the policy. Matching inventory items to sub-limits, totals, gaps and deadline dates are
computed here, so the numbers the family sees are exact and repeatable.
"""

from datetime import date, timedelta
from decimal import Decimal

from pydantic import BaseModel

from app.agents.policy_agent import PolicySummary
from app.models import Household, Item


class SubLimitCheck(BaseModel):
    what: str
    limit: Decimal
    items: list[str]
    items_value: Decimal
    over_by: Decimal


class DeadlineDate(BaseModel):
    what: str
    text: str
    due: date | None
    days_left: int | None


class ClaimCheck(BaseModel):
    loss_date: date | None
    inventory_value: Decimal
    contents_limit: Decimal | None
    contents_gap: Decimal
    deductible: Decimal | None
    settlement: str
    sub_limits: list[SubLimitCheck]
    deadlines: list[DeadlineDate]


def _value(item: Item) -> Decimal:
    return item.total_value or Decimal(0)


# Words for things in well-known sub-limits. The agent names the sub-limit; these make matching reliable
# whatever keywords it picked ("jewelry" alone misses "diamond necklace").
EXPANSIONS = {
    "jewel": [
        "jewelry",
        "ring",
        "necklace",
        "earring",
        "bracelet",
        "pendant",
        "brooch",
        "pearl",
        "diamond",
        "gold",
        "band",
    ],
    "watch": ["watch", "rolex"],
    "silverware": ["silverware", "flatware", "silver"],
    "firearm": ["firearm", "gun", "rifle", "shotgun", "pistol", "revolver"],
    "money": ["cash", "coins", "coin"],
    "fur": ["fur", "mink"],
}


def keywords_for(what: str, keywords: list[str]) -> list[str]:
    text = " ".join([what.lower(), *(k.lower() for k in keywords)])
    extra = [w for trigger, words in EXPANSIONS.items() if trigger in text for w in words]
    return list(dict.fromkeys([*(k.lower() for k in keywords), *extra]))


def score(item: Item, keywords: list[str]) -> int:
    """How many keywords the item's name has. By name only: inventory categories are too coarse for sub-limits
    (a TV is "electronics", but the electronics sub-limit is for gear kept in a car). A word matches its plural."""
    name = item.name.lower()
    words = name.replace(",", " ").replace("'", " ").replace("-", " ").split()
    hits = 0
    for k in dict.fromkeys(k.strip().lower() for k in keywords):
        if (" " in k and k in name) or (
            len(k) >= 3 and any(w == k or (w.startswith(k) and len(w) - len(k) <= 2) for w in words)
        ):
            hits += 1
    return hits


def matches(item: Item, keywords: list[str]) -> bool:
    return score(item, keywords) > 0


def check(summary: PolicySummary, home: Household, items: list[Item], today: date | None = None) -> ClaimCheck:
    today = today or date.today()
    loss = home.disaster_event.declared_at.date() if home.disaster_event else None
    contents = next((c for c in summary.coverages if c.kind == "contents" and c.limit is not None), None)
    total = sum((_value(i) for i in items), Decimal(0))
    limit = Decimal(str(contents.limit)).quantize(Decimal("1")) if contents else None
    # Each item counts under one sub-limit only: the one its name matches best ("gold necklace" is jewelry,
    # not goldware).
    words = [keywords_for(s.what, s.keywords) for s in summary.sub_limits]
    best: dict[int, int] = {}
    for n, item in enumerate(items):
        scores = [score(item, w) for w in words]
        if scores and max(scores) > 0:
            best[n] = scores.index(max(scores))
    subs = []
    for index, s in enumerate(summary.sub_limits):
        hit = [item for n, item in enumerate(items) if best.get(n) == index]
        value = sum((_value(i) for i in hit), Decimal(0))
        cap = Decimal(str(s.limit)).quantize(Decimal("1"))
        subs.append(
            SubLimitCheck(
                what=s.what,
                limit=cap,
                items=[i.name for i in hit],
                items_value=value,
                over_by=max(value - cap, Decimal(0)),
            )
        )
    deadlines = []
    for d in summary.deadlines:
        due = loss + timedelta(days=d.days_after_loss) if loss and d.days_after_loss else None
        deadlines.append(DeadlineDate(what=d.what, text=d.text, due=due, days_left=(due - today).days if due else None))
    deadlines.sort(key=lambda d: (d.due is None, d.due or date.max))
    return ClaimCheck(
        loss_date=loss,
        inventory_value=total,
        contents_limit=limit,
        contents_gap=max(total - limit, Decimal(0)) if limit is not None else Decimal(0),
        deductible=Decimal(str(summary.deductible)) if summary.deductible is not None else None,
        settlement=summary.contents_settlement,
        sub_limits=subs,
        deadlines=deadlines,
    )
