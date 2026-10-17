"""PayPal Subscriptions (Catalog Products, Billing Plans, Subscriptions) and sale refunds, via our REST client.

Used by Reopen Fund "regulars": a monthly pre-payment to a closed local business, for a fixed number of months.
"""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.paypal.rest import PayPalREST


@dataclass
class NewSubscription:
    id: str
    approval_url: str | None
    status: str


async def _create_plan(name: str, description: str, amount: Decimal, months: int, request_id: str) -> str:
    async with PayPalREST.from_settings() as pp:
        product = await pp.request(
            "POST",
            "/v1/catalogs/products",
            json={"name": name[:127], "description": description[:256], "type": "SERVICE", "category": "SERVICES"},
            idempotency_key=f"{request_id}-product",
        )
        plan = await pp.request(
            "POST",
            "/v1/billing/plans",
            json={
                "product_id": product["id"],
                "name": name[:127],
                "description": description[:127],
                "status": "ACTIVE",
                "billing_cycles": [
                    {
                        "frequency": {"interval_unit": "MONTH", "interval_count": 1},
                        "tenure_type": "REGULAR",
                        "sequence": 1,
                        "total_cycles": months,
                        "pricing_scheme": {"fixed_price": {"value": f"{amount:.2f}", "currency_code": "USD"}},
                    }
                ],
                "payment_preferences": {"auto_bill_outstanding": True, "payment_failure_threshold": 2},
            },
            idempotency_key=f"{request_id}-plan",
        )
        return plan["id"]


def create_plan(*, name: str, description: str, amount: Decimal, months: int, request_id: str) -> str:
    """A product and a monthly plan for `months` payments of `amount`. Returns the plan id."""
    return asyncio.run(_create_plan(name, description, amount, months, request_id))


async def _subscribe(plan_id: str, custom_id: str, brand: str, return_url: str, cancel_url: str) -> NewSubscription:
    async with PayPalREST.from_settings() as pp:
        sub = await pp.request(
            "POST",
            "/v1/billing/subscriptions",
            json={
                "plan_id": plan_id,
                "custom_id": custom_id,
                "application_context": {
                    "brand_name": brand[:127],
                    "user_action": "SUBSCRIBE_NOW",
                    "shipping_preference": "NO_SHIPPING",
                    "return_url": return_url,
                    "cancel_url": cancel_url,
                },
            },
            idempotency_key=f"subscribe-{custom_id}",
        )
    link = next((x["href"] for x in sub.get("links", []) if x.get("rel") == "approve"), None)
    return NewSubscription(id=sub["id"], approval_url=link, status=sub.get("status", "APPROVAL_PENDING"))


def subscribe(*, plan_id: str, custom_id: str, brand: str, return_url: str, cancel_url: str) -> NewSubscription:
    """Start a subscription the person approves at `approval_url`; PayPal then sends them to `return_url`."""
    return asyncio.run(_subscribe(plan_id, custom_id, brand, return_url, cancel_url))


async def _status(subscription_id: str) -> str:
    async with PayPalREST.from_settings() as pp:
        return (await pp.request("GET", f"/v1/billing/subscriptions/{subscription_id}"))["status"]


def status(subscription_id: str) -> str:
    """APPROVAL_PENDING | APPROVED | ACTIVE | SUSPENDED | CANCELLED | EXPIRED"""
    return asyncio.run(_status(subscription_id))


async def _cancel(subscription_id: str, reason: str) -> None:
    async with PayPalREST.from_settings() as pp:
        await pp.request("POST", f"/v1/billing/subscriptions/{subscription_id}/cancel", json={"reason": reason[:127]})


def cancel(subscription_id: str, reason: str) -> None:
    asyncio.run(_cancel(subscription_id, reason))


async def _refund_sale(sale_id: str, amount: Decimal) -> str:
    async with PayPalREST.from_settings() as pp:
        refund = await pp.request(
            "POST",
            f"/v1/payments/sale/{sale_id}/refund",
            json={"amount": {"total": f"{amount:.2f}", "currency": "USD"}},
            idempotency_key=f"refund-{sale_id}-{amount:.2f}",
        )
    return refund.get("state", "completed")


def refund_sale(sale_id: str, amount: Decimal) -> str:
    """Refund part or all of one subscription payment."""
    return asyncio.run(_refund_sale(sale_id, amount))


async def _payments(subscription_id: str) -> list[tuple[str, Decimal, Decimal]]:
    end = datetime.now(UTC)
    start = end - timedelta(days=400)
    async with PayPalREST.from_settings() as pp:
        data = await pp.request(
            "GET",
            f"/v1/billing/subscriptions/{subscription_id}/transactions",
            params={"start_time": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "end_time": end.strftime("%Y-%m-%dT%H:%M:%SZ")},
        )
    out = []
    for t in data.get("transactions", []):
        if t.get("status") != "COMPLETED":
            continue
        b = t.get("amount_with_breakdown", {})
        out.append(
            (
                t["id"],
                Decimal(b.get("gross_amount", {}).get("value", "0")),
                Decimal(b.get("fee_amount", {}).get("value", "0")),
            )
        )
    return out


def payments(subscription_id: str) -> list[tuple[str, Decimal, Decimal]]:
    """Completed payments: (sale id, gross, fee)."""
    return asyncio.run(_payments(subscription_id))
