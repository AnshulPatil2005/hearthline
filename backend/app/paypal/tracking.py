"""Shipment tracking on PayPal payments (Orders v2 `track`): when the Shopper's purchase ships, each donor who
paid for that item sees the shipment on their PayPal payment."""

import asyncio

from app.paypal.rest import PayPalREST


async def _add(order_id: str, capture_id: str, tracking_number: str, carrier: str) -> str:
    async with PayPalREST.from_settings() as pp:
        order = await pp.request(
            "POST",
            f"/v2/checkout/orders/{order_id}/track",
            json={
                "capture_id": capture_id,
                "tracking_number": tracking_number,
                "carrier": carrier,
                "notify_payer": False,
            },
            idempotency_key=f"track-{capture_id}-{tracking_number}",
        )
    return order.get("id", order_id)


def add(order_id: str, capture_id: str, tracking_number: str, carrier: str) -> str:
    return asyncio.run(_add(order_id, capture_id, tracking_number, carrier))
