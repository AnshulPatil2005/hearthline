"""Point the PayPal app's webhook at a deployed Hearthline API, subscribed to every event Hearthline handles.

    uv run python -m scripts.paypal_webhook https://hearthline-api.onrender.com

Creates the webhook, or updates the events of the one already at that URL, and prints its id: put it in
PAYPAL_WEBHOOK_ID (signatures are checked against it). The events come from the handlers the code registers
with `@on(...)`, so a new handler only needs this script run again. `--delete` removes the webhook at that URL.
"""

import asyncio
import sys

import app.main  # noqa: F401  (imports every feature module, so every handler is registered)
from app.paypal.rest import PayPalREST
from app.paypal.webhooks import HANDLERS

PATH = "/webhooks/paypal"


def event_types() -> list[str]:
    return sorted(HANDLERS)


async def _find(pp: PayPalREST, url: str) -> dict | None:
    hooks = (await pp.request("GET", "/v1/notifications/webhooks")).get("webhooks", [])
    return next((h for h in hooks if h["url"] == url), None)


async def register(api_base: str) -> tuple[str, str]:
    """Returns (webhook id, "created" | "updated" | "unchanged")."""
    url = api_base.rstrip("/") + PATH
    events = [{"name": name} for name in event_types()]
    async with PayPalREST.from_settings() as pp:
        hook = await _find(pp, url)
        if hook is None:
            hook = await pp.request("POST", "/v1/notifications/webhooks", json={"url": url, "event_types": events})
            return hook["id"], "created"
        if sorted(e["name"] for e in hook.get("event_types", [])) == event_types():
            return hook["id"], "unchanged"  # PayPal rejects a PATCH that changes nothing
        await pp.request(
            "PATCH",
            f"/v1/notifications/webhooks/{hook['id']}",
            json=[{"op": "replace", "path": "/event_types", "value": events}],
        )
        return hook["id"], "updated"


async def delete(api_base: str) -> str | None:
    url = api_base.rstrip("/") + PATH
    async with PayPalREST.from_settings() as pp:
        hook = await _find(pp, url)
        if hook is not None:
            await pp.request("DELETE", f"/v1/notifications/webhooks/{hook['id']}")
        return hook["id"] if hook else None


def main(argv: list[str]) -> None:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1 or not args[0].startswith("https://"):
        sys.exit("Usage: python -m scripts.paypal_webhook https://<your-api-host> [--delete]  (PayPal needs https)")
    if "--delete" in argv:
        removed = asyncio.run(delete(args[0]))
        print(f"Deleted webhook {removed}" if removed else "No webhook at that URL")
        return
    hook_id, what = asyncio.run(register(args[0]))
    print(f"Webhook {what}: {hook_id}  ({len(event_types())} events: {', '.join(event_types())})")
    print(f"Set PAYPAL_WEBHOOK_ID={hook_id} on the API service.")


if __name__ == "__main__":
    main(sys.argv[1:])
