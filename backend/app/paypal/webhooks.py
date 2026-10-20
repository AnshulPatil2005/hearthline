"""PayPal webhooks: verify the signature with PayPal, store each event once, then dispatch it.

PayPal retries deliveries, so storing by event id before processing makes handling idempotent.
Feature modules register handlers with `@on("PAYMENT.CAPTURE.COMPLETED")`.
"""

import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import WebhookEvent, now
from app.paypal.rest import PayPalError, PayPalREST

log = logging.getLogger(__name__)
Handler = Callable[[Session, dict], None]
HANDLERS: dict[str, list[Handler]] = {}

SIGNATURE_HEADERS = {
    "auth_algo": "paypal-auth-algo",
    "cert_url": "paypal-cert-url",
    "transmission_id": "paypal-transmission-id",
    "transmission_sig": "paypal-transmission-sig",
    "transmission_time": "paypal-transmission-time",
}


def on(event_type: str) -> Callable[[Handler], Handler]:
    def register(handler: Handler) -> Handler:
        HANDLERS.setdefault(event_type, []).append(handler)
        return handler

    return register


async def verify_signature(headers: dict[str, str], event: dict) -> bool:
    """Ask PayPal whether this delivery really came from PayPal for our webhook."""
    webhook_id = get_settings().paypal_webhook_id
    if not webhook_id or any(h not in headers for h in SIGNATURE_HEADERS.values()):
        return False
    body = {field: headers[h] for field, h in SIGNATURE_HEADERS.items()}
    body |= {"webhook_id": webhook_id, "webhook_event": event}
    try:
        async with PayPalREST.from_settings() as pp:
            result = await pp.request("POST", "/v1/notifications/verify-webhook-signature", json=body)
    except PayPalError:
        log.exception("Webhook signature verification call failed")
        return False
    return result.get("verification_status") == "SUCCESS"


def handle(db: Session, event: dict, verified: bool) -> WebhookEvent:
    """Store the delivery (once) and run its handlers if it is verified and not yet processed."""
    stored = db.get(WebhookEvent, event["id"])
    if stored is None:
        stored = WebhookEvent(
            id=event["id"], event_type=event["event_type"], resource=event.get("resource", {}), verified=verified
        )
        db.add(stored)
        db.commit()
    elif verified and not stored.verified:
        # An earlier delivery couldn't be verified (say, before PAYPAL_WEBHOOK_ID was set); PayPal's signed
        # redelivery of the same event counts.
        stored.verified = True
        db.commit()
    if not stored.verified or stored.processed_at is not None:
        return stored
    try:
        for handler in HANDLERS.get(stored.event_type, []):
            handler(db, stored.resource)
        stored.processed_at = now()
        stored.error = None
    except Exception as e:  # keep the event for a retry; PayPal will redeliver after a non-2xx too
        db.rollback()
        stored = db.get(WebhookEvent, event["id"])
        stored.error = str(e)[:500]
        log.exception("Webhook %s failed", event["id"])
    db.commit()
    return stored
