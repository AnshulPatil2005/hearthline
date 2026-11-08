from decimal import Decimal

import pytest

from app import audit, ledger
from app.db import SessionLocal
from app.models import Donation, Household
from app.paypal import orders
from app.paypal import webhooks as wh
from app.paypal.orders import Capture
from tests.helpers import client, login_as

SLUG = "rivera-family"


@pytest.fixture
def fake_paypal(monkeypatch):
    created = []

    def create_order(**kwargs):
        created.append(kwargs)
        return f"ORDER-{len(created)}"

    def capture_order(order_id):
        n = order_id.split("-")[1]
        donation_amount = created[int(n) - 1]["amount"]
        return Capture(order_id, f"CAP-{n}", "COMPLETED", donation_amount, Decimal("1.23"), "paypal")

    monkeypatch.setattr(orders, "create_order", create_order)
    monkeypatch.setattr(orders, "capture_order", capture_order)
    return created


def rivera_registry():
    login_as("Elena Rivera")  # seeds the scenario
    return client.get(f"/registries/{SLUG}").json()


def item_named(reg, name):
    return next(i for i in reg["items"] if i["name"] == name)


def test_public_view_hides_the_address():
    reg = rivera_registry()
    assert reg["household_name"] == "Rivera household" and reg["city"] == "Sablewood"
    assert "214 Juniper" not in str(reg) and "lat" not in reg
    assert reg["total_target"] == "1786.00" and reg["total_funded"] == "0.00"
    assert item_named(reg, "Twin mattresses")["target_amount"] == "498.00"


def test_donation_funds_item_and_posts_to_ledger(fake_paypal):
    reg = rivera_registry()
    boots = item_named(reg, "Steel-toe work boots")  # $139

    started = client.post(
        f"/registries/{SLUG}/donations",
        json={"item_id": boots["id"], "amount": "139", "donor_name": "Marcus", "message": "Stay safe"},
    )
    assert started.status_code == 201
    assert fake_paypal[0]["custom_id"] == f"donation:{started.json()['donation_id']}"

    captured = client.post(f"/donations/{started.json()['donation_id']}/capture").json()
    assert captured["status"] == "funded" and captured["remaining"] == "0.00"
    client.post(f"/donations/{started.json()['donation_id']}/capture")  # double click: no double counting

    reg = client.get(f"/registries/{SLUG}").json()
    assert reg["total_funded"] == "139.00" and reg["donor_count"] == 1
    assert reg["recent_donations"][0]["item_name"] == "Steel-toe work boots"
    with SessionLocal() as db:
        hid = db.query(Household).filter_by(name="Rivera household").one().id
        assert ledger.household_available(db, hid) == Decimal("139.00")  # family gets the full gross
        assert ledger.balance(db, ledger.FEES) == Decimal("1.23")  # fee absorbed by the platform
        assert audit.verify_chain(db) == (True, None)

    fund = client.get("/households/me/fund", headers=login_as("Elena Rivera")).json()
    assert fund == {"available": "139.00", "donated": "139.00", "spent": "0.00"}

    with SessionLocal() as db:  # an insurer's advance adds to what's available but isn't negative spending
        ledger.post(
            db,
            kind="insurance_payment",
            description="Dwelling coverage advance",
            household_id=hid,
            paypal_ref=None,
            meta={},
            lines={ledger.CASH: Decimal("500"), ledger.household_fund(hid): Decimal("-500")},
        )
        db.commit()
    fund = client.get("/households/me/fund", headers=login_as("Elena Rivera")).json()
    assert fund == {"available": "639.00", "donated": "139.00", "spent": "0.00"}


def test_donation_limits(fake_paypal):
    reg = rivera_registry()
    laptop = item_named(reg, "School laptop for Maya")  # $449
    too_much = client.post(f"/registries/{SLUG}/donations", json={"item_id": laptop["id"], "amount": "500"})
    assert too_much.status_code == 422 and "449.00" in too_much.json()["detail"]
    assert client.post(f"/registries/{SLUG}/donations", json={"amount": "0.50"}).status_code == 422
    general = client.post(f"/registries/{SLUG}/donations", json={"amount": "25"})  # household fund
    assert general.status_code == 201
    assert client.post("/registries/nope/donations", json={"amount": "5"}).status_code == 404


def test_webhook_captures_when_the_browser_never_came_back(fake_paypal, monkeypatch):
    reg = rivera_registry()
    jackets = item_named(reg, "Winter jackets for the kids")  # $158
    donation_id = client.post(
        f"/registries/{SLUG}/donations", json={"item_id": jackets["id"], "amount": "50", "payment_method": "venmo"}
    ).json()["donation_id"]

    async def verified(headers, event):
        return True

    monkeypatch.setattr(wh, "verify_signature", verified)
    event = {
        "id": "WH-cap-1",
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {
            "id": "CAP-WH",
            "status": "COMPLETED",
            "custom_id": f"donation:{donation_id}",
            "amount": {"currency_code": "USD", "value": "50.00"},
            "seller_receivable_breakdown": {"paypal_fee": {"value": "2.04"}},
        },
    }
    assert client.post("/webhooks/paypal", json=event).status_code == 200
    with SessionLocal() as db:
        d = db.get(Donation, donation_id)
        assert d.status == "captured" and d.paypal_capture_id == "CAP-WH" and d.payment_method == "venmo"
    assert (
        item_named(client.get(f"/registries/{SLUG}").json(), "Winter jackets for the kids")["funded_amount"] == "50.00"
    )


def test_a_capture_and_its_webhook_at_the_same_time_count_the_gift_once():
    """The donor's browser loads the gift, PayPal's webhook captures it, then the browser's capture lands with what it
    loaded before: the item was funded twice for one gift."""
    from app import registry
    from app.models import Donation, RegistryItem
    from app.paypal.orders import Capture

    login_as("Elena Rivera")
    with SessionLocal() as db:
        item = db.query(RegistryItem).filter_by(name="Kitchen starter set").one()
        before = item.funded_amount
        gift = Donation(
            registry_id=item.registry_id, registry_item_id=item.id, amount=Decimal("50.00"), paypal_order_id="O-RACE"
        )
        db.add(gift)
        db.commit()
        gift_id, item_id = gift.id, item.id
    capture = Capture("O-RACE", "CAP-RACE", "COMPLETED", Decimal("50.00"), Decimal("2.00"), "paypal")
    with SessionLocal() as browser, SessionLocal() as webhook:
        stale = browser.get(Donation, gift_id)
        assert stale.status == "created"  # what the browser read before the webhook landed
        registry.apply_capture(webhook, webhook.get(Donation, gift_id), capture)
        registry.apply_capture(browser, stale, capture)
    with SessionLocal() as db:
        assert db.get(RegistryItem, item_id).funded_amount == before + Decimal("50.00")


def test_an_inventory_item_keeps_its_quantity_and_category_on_the_registry():
    """The form sends only the inventory item and a note; its defaults (1, "other") used to win."""
    from app.models import Item

    h = login_as("Elena Rivera")
    with SessionLocal() as db:
        home = db.query(Household).filter_by(name="Rivera household").one()
        chairs = Item(
            household_id=home.id, name="Dining chair", category="furniture", quantity=4, unit_price=Decimal("80")
        )
        db.add(chairs)
        db.commit()
        chairs_id = chairs.id
    r = client.post("/households/me/registry/items", headers=h, json={"inventory_item_id": chairs_id, "note": "Oak"})
    assert r.status_code == 201, r.text
    item = r.json()
    assert (item["quantity"], item["category"], item["target_amount"]) == (4, "furniture", "320.00")


def test_the_last_few_cents_of_an_item_can_be_given():
    """A gift under $1 is refused, unless it's exactly what an item still needs: otherwise the item never finishes."""
    from app import registry
    from app.models import Registry, RegistryItem

    login_as("Elena Rivera")
    with SessionLocal() as db:
        item = db.query(RegistryItem).filter_by(name="Kitchen starter set").one()
        item.funded_amount = item.target_amount - Decimal("0.57")
        db.commit()
        reg = db.get(Registry, item.registry_id)
        with pytest.raises(registry.DonationError):
            registry.new_donation(
                db,
                reg,
                item_id=None,
                amount=Decimal("0.57"),
                donor_name=None,
                message="",
                payment_method="paypal",
                donor=None,
            )
        last = registry.new_donation(
            db,
            reg,
            item_id=item.id,
            amount=Decimal("0.57"),
            donor_name=None,
            message="",
            payment_method="paypal",
            donor=None,
        )
        assert last.amount == Decimal("0.57")
