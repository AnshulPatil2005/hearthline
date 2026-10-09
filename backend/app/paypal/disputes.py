"""PayPal Disputes API (v1 customer disputes), via our REST client.

A payer who disputes a donation or a gift card opens an inquiry, which can become a claim or a chargeback. We read
disputes (webhooks plus a sync), and staff answer with a message, evidence, or by accepting the claim (a refund).
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.paypal.rest import PayPalREST

# The links PayPal puts on a dispute say what the seller may do now; we only offer these three.
ACTIONS = ("send_message", "provide_evidence", "accept_claim")


@dataclass
class DisputeInfo:
    id: str
    reason: str
    status: str
    stage: str
    amount: Decimal
    transaction_id: str | None
    custom_id: str | None
    payer_message: str
    respond_by: datetime | None
    outcome: str | None
    actions: list[str] = field(default_factory=list)


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC).replace(tzinfo=None)


def parse(resource: dict) -> DisputeInfo:
    """A dispute resource (from a webhook or GET) in the shape we store."""
    txn = (resource.get("disputed_transactions") or [{}])[0]
    from_payer = [m.get("content", "") for m in resource.get("messages", []) if m.get("posted_by") == "BUYER"]
    return DisputeInfo(
        id=resource["dispute_id"],
        reason=resource.get("reason", "OTHER"),
        status=resource.get("status", "OPEN"),
        stage=resource.get("dispute_life_cycle_stage", "INQUIRY"),
        amount=Decimal(resource.get("dispute_amount", {}).get("value", "0")),
        transaction_id=txn.get("seller_transaction_id"),
        custom_id=txn.get("custom"),
        payer_message=(from_payer[-1] if from_payer else "")[:2000],
        respond_by=_time(resource.get("seller_response_due_date")),
        outcome=(resource.get("dispute_outcome") or {}).get("outcome_code"),
        actions=[link["rel"] for link in resource.get("links", []) if link.get("rel") in ACTIONS],
    )


async def _recent(days: int) -> list[DisputeInfo]:
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    out: list[DisputeInfo] = []
    async with PayPalREST.from_settings() as pp:
        params: dict | None = {"start_time": since, "page_size": 50}
        path = "/v1/customer/disputes"
        for _ in range(10):  # at most 500 disputes a sync
            page = await pp.request("GET", path, params=params)
            for item in page.get("items", []):
                out.append(parse(await pp.request("GET", f"/v1/customer/disputes/{item['dispute_id']}")))
            nxt = next((x["href"] for x in page.get("links", []) if x.get("rel") == "next"), None)
            if nxt is None:
                break
            path, params = nxt.removeprefix(pp.base_url), None
    return out


def recent(days: int = 180) -> list[DisputeInfo]:
    """Every dispute opened in the last `days` days, with full details."""
    return asyncio.run(_recent(days))


async def _post(path: str, *, json_body: dict | None = None, files: dict | None = None, key: str) -> None:
    async with PayPalREST.from_settings() as pp:
        await pp.request("POST", path, json=json_body, files=files, idempotency_key=key)


def send_message(dispute_id: str, message: str) -> None:
    """Answer an inquiry; PayPal shows the message to the payer."""
    asyncio.run(
        _post(
            f"/v1/customer/disputes/{dispute_id}/send-message",
            json_body={"message": message[:2000]},
            key=f"msg-{dispute_id}-{hashlib.sha256(message.encode()).hexdigest()[:16]}",
        )
    )


def provide_evidence(
    dispute_id: str,
    evidence_type: str,
    notes: str,
    *,
    tracking: list[dict] | None = None,
    refund_ids: list[str] | None = None,
    document: tuple[str, bytes] | None = None,
) -> None:
    """Send our evidence with a note, optionally a tracking number or refund ids, and a PDF of our records."""
    info: dict = {}
    if tracking:
        info["tracking_info"] = tracking
    if refund_ids:
        info["refund_ids"] = [{"refund_id": r} for r in refund_ids]
    evidence = {"evidence_type": evidence_type, "notes": notes[:2000]}
    if info:
        evidence["evidence_info"] = info
    files: dict = {"input": (None, json.dumps({"evidences": [evidence]}), "application/json")}
    if document is not None:
        files["evidence_file"] = (document[0], document[1], "application/pdf")
    asyncio.run(
        _post(f"/v1/customer/disputes/{dispute_id}/provide-evidence", files=files, key=f"evidence-{dispute_id}")
    )


def accept_claim(dispute_id: str, note: str, amount: Decimal) -> None:
    """Agree with the payer; PayPal refunds them `amount` from our balance and closes the dispute."""
    asyncio.run(
        _post(
            f"/v1/customer/disputes/{dispute_id}/accept-claim",
            json_body={
                "note": note[:2000],
                "accept_claim_reason": "COMPANY_POLICY",
                "accept_claim_type": "REFUND",
                "refund_amount": {"currency_code": "USD", "value": f"{amount:.2f}"},
            },
            key=f"accept-{dispute_id}",
        )
    )
