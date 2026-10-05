"""Spike 2: can the Shopper agent pay on its own with a vaulted PayPal wallet?

Step A: a $1 order that asks PayPal to vault the buyer's wallet. You approve it in the
browser as the sandbox *household* (personal) account.
Step B: a second order paid with the vault_id and no buyer interaction - this is what the
Shopper agent does. It ships to a fixed address (the household's verified address).

Usage (from backend/):  uv run python -m spikes.s2_vault_agent_order
Set PAYPAL_SANDBOX_RETAILER_EMAIL to also test paying a different merchant (the stand-in retailer).
"""

import asyncio
import json

from app.config import get_settings
from app.paypal.rest import PayPalError, PayPalREST

VERIFIED_ADDRESS = {
    "address_line_1": "2211 N First St",
    "admin_area_2": "San Jose",
    "admin_area_1": "CA",
    "postal_code": "95131",
    "country_code": "US",
}


def link(order: dict, rel: str) -> str | None:
    return next((lnk["href"] for lnk in order.get("links", []) if lnk["rel"] == rel), None)


async def main() -> None:
    async with PayPalREST.from_settings() as pp:
        # --- Step A: buyer-present order that vaults the wallet ---
        order = await pp.request(
            "POST",
            "/v2/checkout/orders",
            json={
                "intent": "CAPTURE",
                "purchase_units": [
                    {"amount": {"currency_code": "USD", "value": "1.00"}, "description": "Phoenix fund setup"}
                ],
                "payment_source": {
                    "paypal": {
                        "attributes": {
                            "vault": {
                                "store_in_vault": "ON_SUCCESS",
                                "usage_type": "MERCHANT",
                                "customer_type": "CONSUMER",
                            }
                        },
                        "experience_context": {
                            "return_url": "https://example.com/return",
                            "cancel_url": "https://example.com/cancel",
                            "shipping_preference": "NO_SHIPPING",
                            "user_action": "PAY_NOW",
                        },
                    }
                },
            },
        )
        print("Step A order:", order["id"], order["status"])
        print("\nOpen this link, log in as the sandbox HOUSEHOLD account, and approve:\n ", link(order, "payer-action"))
        input("\nPress Enter after approving... ")

        captured = await pp.request("POST", f"/v2/checkout/orders/{order['id']}/capture")
        vault = captured["payment_source"]["paypal"].get("attributes", {}).get("vault", {})
        print("Captured:", captured["status"], "| vault:", json.dumps(vault))
        vault_id = vault.get("id")
        if not vault_id:
            print("FAIL: no vault id returned. Is Vault enabled on the sandbox app?")
            return

        # --- Step B: agent-initiated order, no buyer present ---
        unit: dict = {
            "amount": {"currency_code": "USD", "value": "24.99"},
            "description": "Agent purchase: twin sheet set (registry item #1)",
            "shipping": {"name": {"full_name": "Garcia Household"}, "address": VERIFIED_ADDRESS},
        }
        retailer = get_settings().paypal_sandbox_retailer_email
        if retailer:
            unit["payee"] = {"email_address": retailer}

        try:
            agent_order = await pp.request(
                "POST",
                "/v2/checkout/orders",
                json={
                    "intent": "CAPTURE",
                    "purchase_units": [unit],
                    "payment_source": {"paypal": {"vault_id": vault_id}},
                },
            )
        except PayPalError as e:
            print("FAIL creating agent order:", json.dumps(e.body, indent=2))
            return
        print("\nStep B agent order:", agent_order["id"], agent_order["status"])
        if agent_order["status"] != "COMPLETED":
            agent_order = await pp.request("POST", f"/v2/checkout/orders/{agent_order['id']}/capture")
            print("After capture:", agent_order["status"])
        capture = agent_order["purchase_units"][0]["payments"]["captures"][0]
        print("Capture:", capture["id"], capture["status"], "| payee:", agent_order["purchase_units"][0].get("payee"))
        print("\nPASS if Step B completed without a browser. Record payee behavior in spikes/README.md.")


if __name__ == "__main__":
    asyncio.run(main())
