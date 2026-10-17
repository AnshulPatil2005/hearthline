"""Ask PayPal: the Funds agent answers staff questions about payments with PayPal's own Agent Toolkit tools.

The agent connects to PayPal's MCP server, but code decides which tools it gets: only tools that read. Anything
that moves or changes money (refunds, captures, cancellations, invoices) is never offered, and a call to one is
refused here before PayPal sees it; a person does those in Hearthline, where the rules and two-person checks are.
Every call PayPal answers is written to the audit log. A second tool looks up PayPal ids in Hearthline's records.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import ai, audit
from app.models import (
    Business,
    Donation,
    GiftCard,
    PaymentDispute,
    ReopenCampaign,
    ReopenRegular,
    User,
)

log = logging.getLogger(__name__)

# PayPal MCP tools the agent may use: all of them only read.
READ_TOOLS = {
    "get_order",
    "get_refund",
    "list_disputes",
    "get_dispute",
    "list_transactions",
    "list_invoices",
    "get_invoice",
    "list_products",
    "show_product_details",
    "list_subscription_plans",
    "show_subscription_plan_details",
    "show_subscription_details",
    "get_shipment_tracking",
    "get_merchant_insights",
}
LOOKUP = "hearthline_records"
MAX_STEPS = 6
RESULT_CHARS = 5000

SYSTEM = """You are Hearthline's Funds agent. A relief organization's staff member asks about payments. Hearthline
is a disaster-recovery platform: donors give to families' registries, people buy gift cards and become monthly
"regulars" (PayPal subscriptions) of closed local businesses (Reopen Funds), and payers sometimes open PayPal disputes.

Use hearthline_records to find the PayPal ids behind names (businesses, buyers, donors, disputes), then PayPal's tools
to read what PayPal says about them. You can only read. You cannot refund, capture, cancel or change anything; if
asked to, say which Hearthline page a person uses (the Disputes desk for disputes, Businesses for Reopen Funds).
Ids that start with DEMO- or PP-D-DEMO- are demo records that do not exist in PayPal: don't look them up there, and
say they are demo data. Answer in 2-5 plain sentences with the specific statuses, amounts, dates and ids you found.
If PayPal returns an error or nothing, say so plainly; never guess. Write plain text: no Markdown, no backticks."""

LOOKUP_SPEC = {
    "type": "function",
    "function": {
        "name": LOOKUP,
        "description": "Search Hearthline's own records for PayPal ids: payment disputes, Reopen Fund businesses "
        "(their regulars' subscription plan and subscriptions), gift cards and donations. Search by a name or a word "
        "such as a business, buyer or donor name; an empty search returns the most recent records.",
        "parameters": {
            "type": "object",
            "properties": {"search": {"type": "string", "description": "A name or word; may be empty"}},
            "required": ["search"],
        },
    },
}


class PayPalTools(Protocol):
    async def list_tools(self) -> Any: ...
    async def call_tool(self, name: str, arguments: dict) -> Any: ...


@dataclass
class Step:
    tool: str
    source: str  # paypal | hearthline
    args: dict
    ok: bool
    summary: str


@dataclass
class Answer:
    answer: str
    steps: list[Step] = field(default_factory=list)


def _spec(tool: Any) -> dict:
    schema = dict(tool.input_schema or {"type": "object", "properties": {}})
    schema.pop("$schema", None)
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": (tool.description or "").strip()[:900],
            "parameters": ai._inline_refs(schema),
        },
    }


def _text(result: Any) -> str:
    if getattr(result, "structured_content", None) is not None:
        return json.dumps(result.structured_content)[:RESULT_CHARS]
    return "\n".join(getattr(c, "text", "") for c in result.content)[:RESULT_CHARS]


def _mentions_demo(args: dict) -> bool:
    return any(isinstance(v, str) and ("DEMO-" in v) for v in args.values())


def lookup(db: Session, search: str) -> dict:
    """Hearthline's side: which PayPal ids belong to the names staff use."""
    word = f"%{search.strip()}%" if search.strip() else "%"
    businesses = db.scalars(select(Business).where(Business.name.ilike(word)).limit(5)).all()
    out: dict[str, list] = {"businesses": [], "disputes": [], "gift_cards": [], "donations": []}
    for b in businesses:
        campaign = db.scalar(
            select(ReopenCampaign).where(ReopenCampaign.business_id == b.id).order_by(ReopenCampaign.id.desc())
        )
        regulars = (
            db.scalars(select(ReopenRegular).where(ReopenRegular.campaign_id == campaign.id).limit(10)).all()
            if campaign
            else []
        )
        out["businesses"].append(
            {
                "name": b.name,
                "reopen_fund": campaign.status if campaign else None,
                "regulars_plan_id": campaign.paypal_plan_id if campaign else None,
                "regulars": [
                    {"buyer": r.buyer_name, "status": r.status, "subscription_id": r.paypal_subscription_id}
                    for r in regulars
                ],
            }
        )
    disputes = db.scalars(
        select(PaymentDispute)
        .outerjoin(Donation, PaymentDispute.donation_id == Donation.id)
        .outerjoin(GiftCard, PaymentDispute.gift_card_id == GiftCard.id)
        .where(
            or_(
                PaymentDispute.paypal_dispute_id.ilike(word),
                PaymentDispute.reason.ilike(word),
                Donation.donor_name.ilike(word),
                GiftCard.buyer_name.ilike(word),
            )
        )
        .order_by(PaymentDispute.id.desc())
        .limit(5)
    ).all()
    out["disputes"] = [
        {
            "dispute_id": d.paypal_dispute_id,
            "reason": d.reason,
            "amount": str(d.amount),
            "status_in_hearthline": d.status,
            "transaction_id": d.transaction_id,
        }
        for d in disputes
    ]
    cards = db.scalars(
        select(GiftCard)
        .join(ReopenCampaign)
        .join(Business)
        .where(or_(GiftCard.buyer_name.ilike(word), Business.name.ilike(word)), GiftCard.paypal_order_id.is_not(None))
        .order_by(GiftCard.id.desc())
        .limit(5)
    ).all()
    out["gift_cards"] = [
        {
            "buyer": c.buyer_name,
            "business": c.campaign.business.name,
            "paid": str(c.amount_paid),
            "status": c.status,
            "order_id": c.paypal_order_id,
            "capture_id": c.paypal_capture_id,
        }
        for c in cards
    ]
    gifts = db.scalars(
        select(Donation)
        .where(Donation.donor_name.ilike(word), Donation.paypal_order_id.is_not(None))
        .order_by(Donation.id.desc())
        .limit(5)
    ).all()
    out["donations"] = [
        {
            "donor": g.donor_name,
            "amount": str(g.amount),
            "status": g.status,
            "order_id": g.paypal_order_id,
            "capture_id": g.paypal_capture_id,
        }
        for g in gifts
    ]
    return {k: v for k, v in out.items() if v} or {"found": "nothing matches"}


async def _run(db: Session, question: str, user: User, paypal: PayPalTools) -> Answer:
    offered = [_spec(t) for t in (await paypal.list_tools()).tools if t.name in READ_TOOLS]
    tools = [LOOKUP_SPEC, *offered]
    messages: list[dict] = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}]
    out = Answer(answer="")
    for _ in range(MAX_STEPS):
        message = await asyncio.to_thread(ai.chat, messages, tools=tools)
        if not message.tool_calls:
            out.answer = (message.content or "").strip() or "I couldn't find an answer."
            return out
        messages.append(message.model_dump(exclude_none=True))
        for call in message.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if name == LOOKUP:
                found = lookup(db, str(args.get("search", "")))
                text, step = json.dumps(found), Step(name, "hearthline", args, True, _summary(found))
            elif name not in READ_TOOLS:
                text = f"Refused: {name} is not allowed. Hearthline's agents only read PayPal; people act in the app."
                step = Step(name, "paypal", args, False, "Refused by Hearthline's rules (not a read-only tool)")
            elif _mentions_demo(args):
                text = "Not sent: DEMO- ids are demo records that are not in PayPal."
                step = Step(name, "paypal", args, False, "Skipped: demo record, not in PayPal")
            else:
                result = await paypal.call_tool(name, args)
                text = _text(result)
                failed = bool(getattr(result, "is_error", False)) or '"ok":false' in text.replace(" ", "")
                step = Step(name, "paypal", args, not failed, text[:160])
                audit.record(
                    db,
                    actor_user_id=user.id,
                    action="paypal_agent.read",
                    subject_type="paypal",
                    subject_id=name,
                    data={"args": args, "ok": not failed},
                )
                db.commit()
            out.steps.append(step)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
    out.answer = "I stopped after too many steps without an answer. Try a narrower question."
    return out


def _summary(found: dict) -> str:
    parts = [f"{len(v)} {k.replace('_', ' ')}" for k, v in found.items() if isinstance(v, list)]
    return ", ".join(parts) or "nothing matches"


async def _with_paypal(db: Session, question: str, user: User) -> Answer:
    from mcp import Client
    from mcp.client.sse import sse_client

    from app.paypal.rest import PayPalREST

    async with PayPalREST.from_settings() as pp:
        token = await pp.access_token()
        url = pp.mcp_url
    transport = sse_client(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
    async with Client(transport, mode="legacy") as paypal:
        return await _run(db, question, user, paypal)


def ask(db: Session, question: str, user: User, paypal: PayPalTools | None = None) -> Answer:
    """Answer a staff question. `paypal` replaces PayPal's MCP server in tests."""
    if paypal is not None:
        return asyncio.run(_run(db, question, user, paypal))
    return asyncio.run(_with_paypal(db, question, user))
