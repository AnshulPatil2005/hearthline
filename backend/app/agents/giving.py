"""The giving agent: acting on a donor's standing instruction, it chooses which verified needs to fund and how much,
and explains each gift to the donor. Code has already filtered the needs to those the instruction allows and worked
out the money left; it checks the agent's plan against those limits before anything is paid."""

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

from pydantic import BaseModel

from app import ai

SYSTEM = """You give on behalf of a donor who set a standing instruction to help families after disasters.
You get the donor's instruction in their own words, the money you may give now, the most for any one gift, and a
numbered list of needs that verified families listed. Every need on the list is allowed; your job is to choose.
Prefer gifts that finish an item (so it can be bought now), urgent things (shelter, bedding, school, work, children's
needs), and spreading help across families when the money allows. Never give more to one need than it still needs.
You may give to fewer needs than listed; you may not give to anything that is not listed.
For each gift write one or two plain sentences addressed to the donor as "you": what it pays for, for which
family, and why you chose it (for example, because it matches what you asked for). Don't start with the amount.
summary is one sentence to the donor about this round of giving."""


@dataclass(frozen=True)
class Need:
    item_id: int
    item: str
    note: str
    category: str
    remaining: Decimal
    family: str
    place: str
    disaster: str


@dataclass(frozen=True)
class PlannedGift:
    item_id: int
    amount: Decimal
    reason: str


class _Gift(BaseModel):
    need: int  # the need's number in the list
    amount: float
    reason: str


class _Plan(BaseModel):
    gifts: list[_Gift]
    summary: str


def _cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def check(
    needs: list[Need], wanted: list[tuple[int, Decimal, str]], budget: Decimal, per_gift: Decimal
) -> list[PlannedGift]:
    """Keep only gifts the instruction allows: a listed need, at least $1, within the per-gift cap and what the need
    still needs, one gift per need, and the total within the budget (in the order given)."""
    by_id = {n.item_id: n for n in needs}
    plan, left, seen = [], budget, set()
    for item_id, amount, reason in wanted:
        need = by_id.get(item_id)
        if need is None or item_id in seen:
            continue
        amount = _cents(min(amount, per_gift, need.remaining, left))
        if amount < Decimal("1"):
            continue
        plan.append(PlannedGift(item_id, amount, reason.strip()[:480]))
        seen.add(item_id)
        left -= amount
    return plan


def fallback(needs: list[Need], budget: Decimal, per_gift: Decimal) -> list[PlannedGift]:
    """Without the AI: finish the needs closest to done first, then urgent categories, within the limits."""
    urgent = {"bedding", "clothing", "kitchenware", "furniture"}
    order = sorted(needs, key=lambda n: (n.remaining > per_gift, n.category not in urgent, n.remaining))
    wanted = [
        (
            n.item_id,
            min(per_gift, n.remaining),
            f"{n.item} for the {n.family} in {n.place}: ${n.remaining:,.2f} still needed after {n.disaster}.",
        )
        for n in order
    ]
    return check(needs, wanted, budget, per_gift)


def choose(instruction: str, needs: list[Need], budget: Decimal, per_gift: Decimal) -> tuple[list[PlannedGift], str]:
    """The agent's plan, checked. Raises ai.AIError when no model can answer (the caller uses `fallback`)."""
    listing = "\n".join(
        f"{i}. {n.item} ({n.category}) for the {n.family}, {n.place}, after {n.disaster}: ${n.remaining:,.2f} still"
        f" needed. Family's note: {n.note or '(none)'}"
        for i, n in enumerate(needs)
    )
    prompt = (
        f"Donor's instruction: {instruction or '(no note: help where it matters most)'}\n"
        f"Money you may give now: ${budget:,.2f}. Most for any one gift: ${per_gift:,.2f}.\n\nNeeds:\n{listing}"
    )
    plan = ai.parse(_Plan, system=SYSTEM, content=[ai.text_part(prompt)], max_tokens=2000)
    wanted = [
        (needs[g.need].item_id, Decimal(str(g.amount)), g.reason)
        for g in plan.gifts
        if 0 <= g.need < len(needs) and g.amount > 0
    ]
    return check(needs, wanted, budget, per_gift), plan.summary.strip()[:300]
