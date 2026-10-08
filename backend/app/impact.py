"""Impact reports (the Funds agent): where a donor's money went, and the relief organization's grant report.

Every number comes from the ledger and the database; the AI only writes sentences around numbers it is
given, and the PDF prints the numbers from code. Without an AI provider, a plain template is used.
"""

import hashlib
import json
import logging
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ai, command, ledger
from app.models import (
    AidBatch,
    Case,
    CrewJob,
    DisasterEvent,
    Donation,
    GiftCard,
    LedgerAccount,
    LedgerPosting,
    LedgerTransaction,
    Milestone,
    PriceWatch,
    Purchase,
    ReopenCampaign,
    ReopenTranche,
    User,
)
from app.public_api import TimelineEvent, donation_status
from app.reopen import escrow_balance

log = logging.getLogger(__name__)
_cache: dict[str, str] = {}  # facts hash -> text, so a page view doesn't cost an AI call every time


class Gift(BaseModel):
    kind: str  # donation | gift_card
    id: int
    to: str
    item: str | None
    amount: Decimal
    status: str
    created_at: datetime
    timeline: list[TimelineEvent]
    link: str


class Giving(BaseModel):
    total_given: Decimal
    families_helped: int
    businesses_helped: int
    items_delivered: int
    gifts: list[Gift]
    summary: str
    summary_by_ai: bool


class Story(BaseModel):
    summary: str


DONOR_SYSTEM = """You write a short, warm, factual note for a donor about where their gifts went after a disaster.
Use only the facts given; never invent amounts, names, places or outcomes. 2-4 sentences, plain words, no
exclamation marks, no fundraising pitch. Name what was bought and whether it arrived. Write in English."""


def _ai_text(system: str, facts: dict, fallback: str) -> tuple[str, bool]:
    key = hashlib.sha256((system + json.dumps(facts, sort_keys=True, default=str)).encode()).hexdigest()
    if key in _cache:
        return _cache[key], True
    if not ai.configured():
        return fallback, False
    try:
        text = ai.parse(
            Story, system=system, content=[ai.text_part(json.dumps(facts, default=str))], max_tokens=800
        ).summary
    except ai.AIError:
        log.warning("Impact summary fell back to the template")
        return fallback, False
    _cache[key] = text.strip()
    return _cache[key], True


def giving(db: Session, donor: User, web_url: str, with_ai: bool = False) -> Giving:
    """The donor's gifts. `with_ai` adds the Funds agent's note (slow: the page asks for it separately)."""
    gifts: list[Gift] = []
    donations = db.scalars(
        select(Donation).where(Donation.donor_user_id == donor.id, Donation.status != "failed").order_by(Donation.id)
    )
    for d in donations:
        status = donation_status(db, d.id)
        gifts.append(
            Gift(
                kind="donation",
                id=d.id,
                to=d.rebuild_registry.title,
                item=status.item,
                amount=d.amount,
                status=d.status,
                created_at=d.created_at,
                timeline=status.timeline,
                link=f"{web_url}/r/{d.rebuild_registry.slug}",
            )
        )
    for card in db.scalars(select(GiftCard).where(GiftCard.buyer_user_id == donor.id).order_by(GiftCard.id)):
        if card.status in {"pending", "failed"}:
            continue
        c = card.campaign
        timeline = [TimelineEvent(at=card.activated_at, event=f"Gift card bought for ${card.amount_paid:.2f}")]
        released = [t for t in c.tranches if t.status == "released"]
        timeline += [
            TimelineEvent(at=t.released_at, event=f"{c.business.name} was paid for: {t.title}") for t in released
        ]
        if c.status == "reopened":
            timeline.append(TimelineEvent(at=c.reopened_at, event=f"{c.business.name} reopened"))
        if card.status == "refunded":
            timeline.append(TimelineEvent(at=c.refunded_at, event=f"Refunded ${card.refunded_amount:.2f}"))
        gifts.append(
            Gift(
                kind="gift_card",
                id=card.id,
                to=c.business.name,
                item=f"Gift card worth ${card.face_value:.2f}",
                amount=card.amount_paid,
                status=card.status,
                created_at=card.created_at,
                timeline=timeline,
                link=f"{web_url}/card/{card.code}",
            )
        )
    paid = [g for g in gifts if g.status in {"captured", "active", "refunded"}]
    delivered = sum(1 for g in paid if any("Delivered" in e.event for e in g.timeline))
    facts = {
        "donor_first_name": donor.name.split()[0],
        "gifts": [
            {"to": g.to, "item": g.item, "amount": g.amount, "what_happened": [e.event for e in g.timeline]}
            for g in paid
        ],
    }
    fallback = (
        f"You've given ${sum((g.amount for g in paid), Decimal(0)):,.2f} in {len(paid)} gift(s). "
        "Each one below shows what it paid for and where it is now."
        if paid
        else "Your gifts will show up here, with what each one paid for and where it is now."
    )
    summary, by_ai = _ai_text(DONOR_SYSTEM, facts, fallback) if paid and with_ai else (fallback, False)
    return Giving(
        total_given=sum((g.amount for g in paid), Decimal(0)),
        families_helped=len({g.to for g in paid if g.kind == "donation"}),
        businesses_helped=len({g.to for g in paid if g.kind == "gift_card"}),
        items_delivered=delivered,
        gifts=list(reversed(gifts)),
        summary=summary,
        summary_by_ai=by_ai,
    )


# --- The organization's grant report ----------------------------------------------------------------


def report_numbers(db: Session, event: DisasterEvent) -> dict:
    overview = command.summary(db)
    cash_aid = ledger.balance(db, ledger.CASH_AID)  # paid out, net of anything PayPal returned
    cash_aid_homes = db.scalar(
        select(func.count(func.distinct(LedgerTransaction.household_id)))
        .join(LedgerPosting, LedgerPosting.transaction_id == LedgerTransaction.id)
        .join(LedgerAccount, LedgerAccount.id == LedgerPosting.account_id)
        .where(LedgerAccount.code == ledger.CASH_AID, LedgerPosting.amount > 0)
    )
    donations = list(db.scalars(select(Donation).where(Donation.status == "captured")))
    purchases = list(db.scalars(select(Purchase).where(Purchase.status.in_(["paid", "shipped", "delivered"]))))
    refused = sum(len(p.refused_offers or []) for p in db.scalars(select(Purchase)))
    cases = list(db.scalars(select(Case)))
    campaigns = list(db.scalars(select(ReopenCampaign)))
    released = sum(
        (t.amount for t in db.scalars(select(ReopenTranche).where(ReopenTranche.status == "released"))), Decimal(0)
    )
    refunded = sum(
        (c.refunded_amount for c in db.scalars(select(GiftCard).where(GiftCard.status == "refunded"))), Decimal(0)
    )
    return {
        "disaster": event.name,
        "declared": event.declared_at.date().isoformat()
        if isinstance(event.declared_at, datetime)
        else str(event.declared_at),
        "report_date": date.today().isoformat(),
        "households_registered": overview["households"],
        "homes_destroyed": overview["destroyed"],
        "households_verified": overview["verified"],
        "help_received_total": Decimal(str(overview["help_received"])),
        "still_needed_total": Decimal(str(overview["unmet_need"])),
        "cash_aid_paid": cash_aid,
        "cash_aid_households": cash_aid_homes,
        "aid_batches_sent": db.scalar(select(func.count(AidBatch.id)).where(AidBatch.status == "sent")),
        "registry_gifts": len(donations),
        "registry_gifts_total": sum((d.amount for d in donations), Decimal(0)),
        "items_bought": len(purchases),
        "items_delivered": sum(1 for p in purchases if p.status == "delivered"),
        "gouging_offers_refused": refused,
        "cases_reviewed": sum(1 for c in cases if c.status in {"approved", "rejected"}),
        "cases_rejected": sum(1 for c in cases if c.status == "rejected"),
        "contractor_milestones_paid": db.scalar(select(func.count(Milestone.id)).where(Milestone.status == "paid")),
        "reopen_funds": len(campaigns),
        "reopen_raised": sum((c.raised for c in campaigns), Decimal(0)),
        "reopen_released_to_businesses": released,
        "reopen_refunded_to_buyers": refunded,
        "reopen_in_escrow": sum((escrow_balance(db, c.id) for c in campaigns), Decimal(0)),
        "crew_jobs_done": db.scalar(select(func.count(CrewJob.id)).where(CrewJob.status == "done")),
        "crew_jobs_scheduled": db.scalar(select(func.count(CrewJob.id)).where(CrewJob.status == "scheduled")),
        "prices_tracked": db.scalar(select(func.count(PriceWatch.id))),
        "prices_over_limit": db.scalar(select(func.count(PriceWatch.id)).where(PriceWatch.status == "gouging")),
        "fictional_demo_data": bool(event.is_fictional),
    }


class Narrative(BaseModel):
    headline: str
    paragraphs: list[str]


GRANT_SYSTEM = """You write the narrative section of a relief organization's grant report to its funders.
Use only the facts given, copying figures exactly as written; never invent figures, names or outcomes, and
never compare or combine two figures unless a fact states the relation. Be specific and sober: what was done,
for how many people, what is still needed, and how money was safeguarded (human review, two-person approval
of batch payments, escrow, price-gouging checks). Leave out facts whose value is 0 or $0. A headline of at
most 12 words, then 3 paragraphs of at most 4 sentences each.
If the facts say the data is fictional, the last paragraph must say the figures are fictional demo data."""

FACT_LABELS = {
    "households_registered": "Households registered with the relief network",
    "homes_destroyed": "Of those, households whose home was destroyed",
    "households_verified": "Households verified to receive cash aid (any level of damage)",
    "help_received_total": "Help households have received so far (gifts, insurance and cash aid)",
    "still_needed_total": "Estimated losses still not covered",
    "cash_aid_paid": "Cash aid paid by the relief network",
    "cash_aid_households": "Households that received cash aid",
    "aid_batches_sent": "Cash aid batches sent after a second person approved them",
    "registry_gifts": "Gifts to families' registries",
    "registry_gifts_total": "Value of registry gifts",
    "items_bought": "Items bought for families by the Shopper agent",
    "items_delivered": "Of those, items delivered",
    "gouging_offers_refused": "Offers the Shopper refused for price gouging",
    "cases_reviewed": "Aid cases decided by human reviewers",
    "cases_rejected": "Of those, cases rejected (fraud or not eligible)",
    "contractor_milestones_paid": "Contractor milestones paid from escrow",
    "reopen_funds": "Local businesses with a Reopen Fund",
    "reopen_raised": "Raised for businesses through gift-card pre-sales",
    "reopen_released_to_businesses": "Released to businesses after staff approval",
    "reopen_refunded_to_buyers": "Refunded to gift-card buyers when a business missed its reopening date",
    "reopen_in_escrow": "Gift-card money still held in escrow",
    "crew_jobs_done": "Volunteer crew visits finished",
    "crew_jobs_scheduled": "Volunteer crew visits still scheduled",
    "prices_tracked": "Essential prices tracked for gouging",
    "prices_over_limit": "Of those, prices more than 10% above their pre-disaster level",
}
MONEY_KEYS = {
    "help_received_total",
    "still_needed_total",
    "cash_aid_paid",
    "registry_gifts_total",
    "reopen_raised",
    "reopen_released_to_businesses",
    "reopen_refunded_to_buyers",
    "reopen_in_escrow",
}


def facts_for_ai(numbers: dict) -> dict:
    """Plain labels and formatted values, so the model can't misread what a number counts."""
    facts = {
        "Disaster": numbers["disaster"],
        "Emergency declared": numbers["declared"],
        "Report date": numbers["report_date"],
    }
    for key, label in FACT_LABELS.items():
        value = numbers[key]
        facts[label] = f"${Decimal(str(value)):,.0f}" if key in MONEY_KEYS else f"{value:,}"
    facts["Data"] = "fictional demo data" if numbers["fictional_demo_data"] else "real"
    return facts


def grant_narrative(numbers: dict) -> tuple[Narrative, bool]:
    fallback = Narrative(
        headline=f"{numbers['disaster']}: response report",
        paragraphs=[
            f"{numbers['households_registered']:,} households registered after the {numbers['disaster']}; "
            f"{numbers['homes_destroyed']:,} homes were destroyed and {numbers['households_verified']:,} households "
            "are verified to receive cash aid.",
            f"Families have received ${numbers['help_received_total']:,.0f} in help so far, including "
            f"${numbers['cash_aid_paid']:,.0f} of cash aid. ${numbers['still_needed_total']:,.0f} is still needed.",
            "Every payment was approved by people: reviewers check claims, a second person approves batch payments, "
            "and contractor and business money waits in escrow."
            + (" These figures are fictional demo data." if numbers["fictional_demo_data"] else ""),
        ],
    )
    key = hashlib.sha256(json.dumps(numbers, sort_keys=True, default=str).encode()).hexdigest()
    if key in _cache:
        return Narrative.model_validate_json(_cache[key]), True
    if not ai.configured():
        return fallback, False
    try:
        result = ai.parse(
            Narrative, system=GRANT_SYSTEM, content=[ai.text_part(json.dumps(facts_for_ai(numbers)))], max_tokens=1500
        )
    except ai.AIError:
        return fallback, False
    _cache[key] = result.model_dump_json()
    return result, True
