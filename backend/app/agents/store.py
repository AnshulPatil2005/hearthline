"""A local store's pricing agent. It answers the Shopper (Hearthline's buying agent) for the store, within the owner's
rules: the AI chooses an opening price between the item's floor and its list price, guided by the owner's own
instructions and the best online price the Shopper mentions, and writes the store's replies. Code holds every price
to that range; on a counter-offer, code accepts at or above the floor and otherwise answers with the floor."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from app import ai

SYSTEM = """You set prices for a small local store selling to families who lost their homes in a disaster. The buyer
is Hearthline's Shopper, an AI agent spending donated money for one family. Follow the store owner's instructions.
You get the item, its list price, the lowest price the owner allows (the floor), the quantity, delivery time, and the
best online price the Shopper found, if any. Choose the unit price to quote, between the floor and the list price:
the owner wants the sale and wants to help, and also has to cover costs. Quoting at or under the online price
usually wins; you never have to go to the floor.
message is one or two plain, friendly sentences from the store to the Shopper: the price, delivery, and, if it fits,
a word about the family or the town. No exclamation marks, no haggling theatrics."""

REPLY = """You write one or two plain, friendly sentences for a small local store, replying to Hearthline's Shopper
(an AI agent buying for a family who lost their home in a disaster). Follow the store owner's instructions. Say
whether the store accepts the Shopper's counter-offer and the price that stands. No exclamation marks."""


@dataclass(frozen=True)
class Answer:
    unit_price: Decimal
    message: str
    by_ai: bool


class _Opening(BaseModel):
    unit_price: float
    message: str


class _Reply(BaseModel):
    message: str


def _cents(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def clamp(price: Decimal, floor: Decimal, list_price: Decimal) -> Decimal:
    return _cents(min(max(price, floor), list_price))


def opening(
    *,
    store: str,
    owner_note: str,
    item: str,
    need: str,
    list_price: Decimal,
    floor: Decimal,
    quantity: int,
    delivery_days: int,
    competing: Decimal | None,
) -> Answer:
    """The store's first quote. Without the AI, the list price."""
    prompt = (
        f"Store: {store}\nOwner's instructions: {owner_note or '(none)'}\n"
        f"Item: {item} (the family needs: {need})\nQuantity: {quantity}\n"
        f"List price: ${list_price} a unit. Floor: ${floor} a unit. Delivery: {delivery_days} day(s) in town.\n"
        f"Best online price the Shopper found: {f'${competing} a unit' if competing else 'none'}"
    )
    try:
        answer = ai.parse(_Opening, system=SYSTEM, content=[ai.text_part(prompt)], max_tokens=600)
        price = clamp(Decimal(str(answer.unit_price)), floor, list_price)
        return Answer(price, answer.message.strip()[:400], True)
    except (ai.AIError, ValueError, ArithmeticError):
        message = f"We can do ${list_price:,.2f} each for {quantity}, delivered in town in {delivery_days} day(s)."
        return Answer(_cents(list_price), message, False)


def reply_to_counter(
    *, store: str, owner_note: str, item: str, counter: Decimal, floor: Decimal, current: Decimal
) -> tuple[Answer, bool]:
    """Code decides: accept at or above the floor; otherwise the floor is the final price. The AI only writes it.
    Returns the answer and whether the counter was accepted."""
    accepted = counter >= floor
    price = _cents(counter if accepted else min(floor, current))
    decision = f"accept ${counter} a unit" if accepted else f"decline; the lowest the store can do is ${price} a unit"
    prompt = (
        f"Store: {store}\nOwner's instructions: {owner_note or '(none)'}\nItem: {item}\n"
        f"The Shopper offered ${counter} a unit. The store will {decision}."
    )
    try:
        text = ai.parse(_Reply, system=REPLY, content=[ai.text_part(prompt)], max_tokens=300).message.strip()[:400]
        return Answer(price, text, True), accepted
    except ai.AIError:
        text = (
            f"We can do ${price:,.2f} each. Thank you for buying local."
            if accepted
            else f"We can't go below ${price:,.2f} each, but that's our final price."
        )
        return Answer(price, text, False), accepted
