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
