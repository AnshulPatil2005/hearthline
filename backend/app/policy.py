"""Spending rules for the Shopper agent. Plain code, deliberately outside the AI.

The AI may only *propose* a purchase. Every proposal passes through `evaluate`, and only
allowed proposals can be paid. Payees are never chosen by the AI: money only goes to
retailers on the allowlist, resolved here.
"""

from dataclasses import asdict, dataclass, field
from decimal import Decimal

from app.gouging import LIMIT_PERCENT, Verdict

PER_ITEM_MAX = Decimal("1000.00")  # no single purchase above this
PER_DAY_MAX = Decimal("2500.00")  # per household, across all purchases
APPROVAL_OVER = Decimal("300.00")  # above this the household must approve first
MAX_OVER_MEDIAN = Decimal("1.5")  # chosen price may not exceed 1.5x the median of comparable offers
MIN_AI_CONFIDENCE = 0.6  # below this the household must approve first
BLOCKED_CATEGORIES = {"gift_card", "jewelry", "alcohol", "tobacco", "weapons", "cash_equivalent"}


@dataclass
class Check:
    rule: str
    passed: bool
    detail: str


@dataclass
class Decision:
    allowed: bool
    needs_approval: bool
    checks: list[Check] = field(default_factory=list)

    def as_json(self) -> list[dict]:
        return [asdict(c) for c in self.checks]


@dataclass
class Proposal:
    total: Decimal
    category: str
    retailer: str
    unit_price: Decimal
    comparable_median: Decimal
    ai_confidence: float


def evaluate(
    p: Proposal,
    *,
    item_funded: Decimal,
    available_funds: Decimal,
    spent_today: Decimal,
    allowed_retailers: set[str],
    ship_to_verified: bool,
    gouging: Verdict | None = None,
) -> Decision:
    def money(v: Decimal) -> str:
        return f"${v:,.2f}"

    checks = [
        Check(
            "funds_available",
            p.total <= available_funds,
            f"{money(p.total)} needed, {money(available_funds)} held for the household",
        ),
        Check(
            "within_item_funding",
            p.total <= item_funded,
            f"{money(p.total)} vs {money(item_funded)} donated for this item",
        ),
        Check("per_item_limit", p.total <= PER_ITEM_MAX, f"limit {money(PER_ITEM_MAX)} per purchase"),
        Check(
            "daily_limit",
            spent_today + p.total <= PER_DAY_MAX,
            f"{money(spent_today)} already spent today, limit {money(PER_DAY_MAX)}",
        ),
        Check("category_allowed", p.category not in BLOCKED_CATEGORIES, f"category '{p.category}'"),
        Check(
            "known_retailer",
            p.retailer in allowed_retailers,
            f"{p.retailer} {'is' if p.retailer in allowed_retailers else 'is not'} an approved retailer",
        ),
        Check("ships_to_verified_address", ship_to_verified, "ships only to the household's verified address"),
        Check(
            "price_sanity",
            p.unit_price <= p.comparable_median * MAX_OVER_MEDIAN,
            f"{money(p.unit_price)} vs {money(p.comparable_median)} median of comparable offers",
        ),
    ]
    if gouging is not None:  # only while the disaster's price protection is in force
        checks.append(
            Check(
                "no_price_gouging",
                not gouging.gouging,
                f"{gouging.explain()}; the limit is +{LIMIT_PERCENT:.0f}% (California Penal Code 396)",
            )
        )
    allowed = all(c.passed for c in checks)
    needs_approval = allowed and (p.total > APPROVAL_OVER or p.ai_confidence < MIN_AI_CONFIDENCE)
    return Decision(allowed=allowed, needs_approval=needs_approval, checks=checks)
