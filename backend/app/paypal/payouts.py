"""PayPal Payouts (not covered by the Server SDK or the Agent Toolkit), via our REST client."""

import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.paypal.rest import PayPalError, PayPalREST


@dataclass
class PayoutResult:
    batch_id: str
    status: str


def batch_id_for(kind: str, record_id: int, created_at: datetime) -> str:
    """Stable for one record (a retry reuses it, so PayPal never pays twice) yet unique across databases,
    because PayPal remembers sender batch ids for 30 days."""
    return f"hearthline-{kind}-{record_id}-{int(created_at.timestamp())}"


def _existing_batch(error: PayPalError) -> str | None:
    """PayPal's reply when this exact batch was already submitted: return that batch's id."""
    for detail in (error.body or {}).get("details", []) if isinstance(error.body, dict) else []:
        if detail.get("field") == "SENDER_BATCH_ID" and "already exists" in detail.get("issue", ""):
            for link in detail.get("link", []):
                return link["href"].rstrip("/").rsplit("/", 1)[-1]
    return None


def failure_reason(error: PayPalError, what: str = "the payment") -> str:
    """A message for the person who pressed the button. Nothing was sent when this is shown."""
    name = error.body.get("name") if isinstance(error.body, dict) else None
    if name == "INSUFFICIENT_FUNDS":
        return (
            f"The relief fund's PayPal balance can't cover {what} right now. "
            "Nothing was sent; try again once it's topped up."
        )
    return f"PayPal couldn't send {what} ({error.status}). Try again in a moment."


async def _send(items: list[dict], batch_id: str, subject: str) -> PayoutResult:
    async with PayPalREST.from_settings() as pp:
        try:
            created = await pp.request(
                "POST",
                "/v1/payments/payouts",
                json={"sender_batch_header": {"sender_batch_id": batch_id, "email_subject": subject}, "items": items},
                idempotency_key=batch_id,
            )
        except PayPalError as e:
            existing = _existing_batch(e)
            if existing is None:
                raise
            return PayoutResult(batch_id=existing, status="ALREADY_SENT")
    header = created["batch_header"]
    return PayoutResult(batch_id=header["payout_batch_id"], status=header["batch_status"])


def send_payouts(payments: list[tuple[str, Decimal, str, str]], *, batch_id: str, subject: str) -> PayoutResult:
    """payments: (receiver email, amount, note, our item id). `batch_id` makes retries safe."""
    items = [
        {
            "recipient_type": "EMAIL",
            "receiver": email,
            "amount": {"value": f"{amount:.2f}", "currency": "USD"},
            "note": note[:4000],
            "sender_item_id": item_id,
        }
        for email, amount, note, item_id in payments
    ]
    return asyncio.run(_send(items, batch_id, subject))


@dataclass
class PayoutItemStatus:
    sender_item_id: str
    payout_item_id: str
    status: str  # PayPal's transaction_status: PENDING, SUCCESS, UNCLAIMED, RETURNED, FAILED, ...


async def _batch_items(batch_id: str) -> list[PayoutItemStatus]:
    out, page = [], 1
    async with PayPalREST.from_settings() as pp:
        while True:
            data = await pp.request(
                "GET",
                f"/v1/payments/payouts/{batch_id}",
                params={"page": page, "page_size": 1000, "total_required": "true"},
            )
            for item in data.get("items", []):
                out.append(
                    PayoutItemStatus(
                        sender_item_id=item.get("payout_item", {}).get("sender_item_id", ""),
                        payout_item_id=item["payout_item_id"],
                        status=item.get("transaction_status", "PENDING"),
                    )
                )
            if page >= (data.get("total_page") or 1):
                return out
            page += 1


def batch_items(batch_id: str) -> list[PayoutItemStatus]:
    """Where each payment in a PayPal payout batch stands now."""
    return asyncio.run(_batch_items(batch_id))
