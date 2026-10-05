"""Spike 3: send one Payouts batch (cash aid / milestone / reimbursement) to several receivers.

Usage (from backend/):  uv run python -m spikes.s3_payouts_batch
Receivers come from PAYPAL_SANDBOX_PAYOUT_RECEIVERS (comma-separated sandbox personal emails).
"""

import asyncio
import uuid

from app.config import get_settings
from app.paypal.rest import PayPalREST

NOTES = ["Phoenix cash aid", "Volunteer reimbursement", "Milestone 1: demolition"]


async def main() -> None:
    receivers = [e.strip() for e in get_settings().paypal_sandbox_payout_receivers.split(",") if e.strip()]
    if not receivers:
        raise SystemExit("Set PAYPAL_SANDBOX_PAYOUT_RECEIVERS in backend/.env")

    async with PayPalREST.from_settings() as pp:
        batch_id = f"phoenix-spike-{uuid.uuid4().hex[:12]}"
        created = await pp.request(
            "POST",
            "/v1/payments/payouts",
            json={
                "sender_batch_header": {
                    "sender_batch_id": batch_id,
                    "email_subject": "You have a payment from Phoenix",
                    "email_message": "Funds released after human review.",
                },
                "items": [
                    {
                        "recipient_type": "EMAIL",
                        "receiver": email,
                        "amount": {"value": f"{25 * (i + 1)}.00", "currency": "USD"},
                        "note": NOTES[i % len(NOTES)],
                        "sender_item_id": f"{batch_id}-{i}",
                    }
                    for i, email in enumerate(receivers)
                ],
            },
            idempotency_key=batch_id,
        )
        payout_batch_id = created["batch_header"]["payout_batch_id"]
        print("Batch created:", payout_batch_id, created["batch_header"]["batch_status"])

        for _ in range(20):
            await asyncio.sleep(3)
            batch = await pp.request("GET", f"/v1/payments/payouts/{payout_batch_id}")
            status = batch["batch_header"]["batch_status"]
            print("  status:", status)
            if status in {"SUCCESS", "DENIED", "CANCELED"}:
                break

        for item in batch.get("items", []):
            payout = item["payout_item"]
            print(f"  {payout['receiver']:<35} {payout['amount']['value']:>8} {item['transaction_status']}")


if __name__ == "__main__":
    asyncio.run(main())
