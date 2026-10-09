import asyncio

from scripts import paypal_webhook


class FakePayPal:
    """PayPal's webhooks API in memory."""

    def __init__(self, hooks):
        self.hooks = hooks
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, path, json=None, **kw):
        self.sent.append((method, path))
        if method == "GET":
            return {"webhooks": self.hooks}
        if method == "POST":
            self.hooks.append({"id": "WH-NEW", "url": json["url"], "event_types": json["event_types"]})
            return self.hooks[-1]
        return None


def run(monkeypatch, hooks):
    fake = FakePayPal(hooks)
    monkeypatch.setattr(paypal_webhook.PayPalREST, "from_settings", classmethod(lambda cls: fake))
    return asyncio.run(paypal_webhook.register("https://api.example.org/")), fake


def test_events_are_every_registered_handler():
    events = paypal_webhook.event_types()
    for name in ("PAYMENT.CAPTURE.COMPLETED", "PAYMENT.SALE.COMPLETED", "CUSTOMER.DISPUTE.CREATED"):
        assert name in events
    assert "PAYMENT.PAYOUTS-ITEM.REVERSED" not in events  # PayPal has no such event and rejects the whole list


def test_creates_then_leaves_alone_then_updates(monkeypatch):
    (hook_id, what), fake = run(monkeypatch, [])
    assert (hook_id, what) == ("WH-NEW", "created")
    assert fake.hooks[0]["url"] == "https://api.example.org/webhooks/paypal"

    (_, what), fake = run(monkeypatch, fake.hooks)
    assert what == "unchanged" and [m for m, _ in fake.sent] == ["GET"]

    stale = [{"id": "WH-OLD", "url": "https://api.example.org/webhooks/paypal", "event_types": [{"name": "X"}]}]
    (hook_id, what), fake = run(monkeypatch, stale)
    assert (hook_id, what) == ("WH-OLD", "updated") and fake.sent[-1] == ("PATCH", "/v1/notifications/webhooks/WH-OLD")
