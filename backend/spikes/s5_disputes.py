"""Spike 5: can we drive a dispute to a verdict in the sandbox (for the contractor mediation demo)?

1. As the sandbox buyer, open a dispute on a captured payment at
   https://www.sandbox.paypal.com -> Activity -> transaction -> "Report a problem".
2. List disputes:          uv run python -m spikes.s5_disputes
3. Settle one (sandbox):   uv run python -m spikes.s5_disputes <dispute_id> buyer|seller
"""

import asyncio
import json
import sys

from app.paypal.rest import PayPalError, PayPalREST


async def main() -> None:
    async with PayPalREST.from_settings() as pp:
        if len(sys.argv) == 1:
            data = await pp.request("GET", "/v1/customer/disputes", params={"page_size": 10})
            items = data.get("items", [])
            print(f"{len(items)} disputes")
            for d in items:
                print(f"  {d['dispute_id']}  {d['status']:<28} {d.get('reason', '')}  {d.get('dispute_amount', {})}")
            return

        dispute_id, side = sys.argv[1], sys.argv[2]
        print(json.dumps(await pp.request("GET", f"/v1/customer/disputes/{dispute_id}"), indent=2)[:2000])
        outcome = {"buyer": "BUYER_FAVOR", "seller": "SELLER_FAVOR"}[side]
        try:
            # Sandbox-only endpoint that settles a dispute immediately.
            result = await pp.request(
                "POST", f"/v1/customer/disputes/{dispute_id}/adjudicate", json={"adjudication_outcome": outcome}
            )
            print("Adjudicated:", json.dumps(result, indent=2))
        except PayPalError as e:
            print("Adjudicate failed:", e.status, json.dumps(e.body, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
