"""PayPal Payouts (not covered by the Server SDK or the Agent Toolkit), via our REST client."""

import asyncio
from dataclasses import dataclass
from decimal import Decimal

from app.paypal.rest import PayPalREST


@dataclass
class PayoutResult:
    batch_id: str
    status: str


async def _send(items: list[dict], batch_id: str, subject: str) -> PayoutResult:
    async with PayPalREST.from_settings() as pp:
        created = await pp.request(
            "POST",
            "/v1/payments/payouts",
            json={"sender_batch_header": {"sender_batch_id": batch_id, "email_subject": subject}, "items": items},
            idempotency_key=batch_id,
        )
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
