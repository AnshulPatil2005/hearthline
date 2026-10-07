from decimal import Decimal as D

import pytest

from app import audit, ledger, registry, shopping
from app.agents import shopper
from app.agents.shopper import Candidate, ShopperChoice
from app.db import SessionLocal
from app.models import Donation, Household, Purchase, RegistryItem
from app.paypal import payouts
from app.paypal.orders import Capture
from tests.helpers import client, login_as

CANDIDATES = {
    "Steel-toe work boots": [
        Candidate("p1", "Mens Steel Toe Work Boot", "homedepot.com", D("129.99"), "https://x/p1"),
        Candidate("p2", "Waterproof Steel Toe Boot", "walmart.com", D("89.00"), "https://x/p2"),
        Candidate("p3", "Leather Steel Toe Boot", "lowes.com", D("139.00"), "https://x/p3"),
    ],
    "Twin mattresses": [
        Candidate("m1", "8 in. Memory Foam Twin Mattress", "walmart.com", D("229.00"), "https://x/m1"),
        Candidate("m2", "Hybrid Twin Mattress", "target.com", D("249.00"), "https://x/m2"),
    ],
}


@pytest.fixture
def fakes(monkeypatch):
    paid = []

    def send_payouts(payments, batch_id, subject):
        paid.append((payments, batch_id))
        return payouts.PayoutResult(batch_id=f"BATCH-{len(paid)}", status="PENDING")

    monkeypatch.setattr(shopper, "find_candidates", lambda query, budget: CANDIDATES.get(query, []))
    monkeypatch.setattr(
        shopper,
        "choose",
        lambda need, note, qty, budget, cands: ShopperChoice(
            choice=0, reasoning=f"Best match for {need}", confidence=0.92
        ),
    )
    monkeypatch.setattr(payouts, "send_payouts", send_payouts)
    monkeypatch.setattr(shopping, "start_auto_shop", shopping.shop_item)  # run inline in tests
    return paid


def fund(item_name: str) -> int:
    """Fully fund a registry item through the real capture path; returns the item id."""
    login_as("Elena Rivera")
    with SessionLocal() as db:
        item = db.query(RegistryItem).filter_by(name=item_name).one()
        donation = Donation(
            registry_id=item.registry_id,
            registry_item_id=item.id,
            amount=item.target_amount,
            paypal_order_id=f"O-{item.id}",
        )
        db.add(donation)
        db.commit()
        capture = Capture(f"O-{item.id}", f"CAP-{item.id}", "COMPLETED", item.target_amount, D("3.00"), "paypal")
        registry.apply_capture(db, donation, capture)
        return item.id


def test_funded_item_is_bought_automatically(fakes):
    item_id = fund("Steel-toe work boots")  # $139, under the $300 approval threshold
    p = client.get("/households/me/purchases", headers=login_as("Elena Rivera")).json()[0]
    assert p["status"] == "paid" and p["retailer"] == "homedepot.com" and p["total"] == "129.99"
    assert all(c["passed"] for c in p["policy_checks"]) and len(p["policy_checks"]) == 8
    assert p["ai_reasoning"] and p["paypal_ref"] == "BATCH-1"
    payee, amount, _note, _ref = fakes[0][0][0]
    assert payee == shopping.STANDIN_RETAILER and amount == D("129.99")  # payee chosen by code, not the AI
    with SessionLocal() as db:
        assert db.get(RegistryItem, item_id).status == "purchased"
        hid = db.query(Household).filter_by(name="Rivera household").one().id
        assert ledger.household_available(db, hid) == D("9.01")  # 139 donated - 129.99 spent
        assert audit.verify_chain(db) == (True, None)


def test_large_purchase_waits_for_the_household(fakes):
    fund("Twin mattresses")  # 2 x $229 = $458 > $300
    h = login_as("Elena Rivera")
    p = client.get("/households/me/purchases", headers=h).json()[0]
    assert p["status"] == "awaiting_approval" and fakes == []
    approved = client.post(f"/purchases/{p['id']}/approve", headers=h).json()
    assert approved["status"] == "paid" and approved["total"] == "458.00"
    assert client.post(f"/purchases/{p['id']}/approve", headers=h).status_code == 409


def test_blocked_purchase_is_never_paid(fakes, monkeypatch):
    monkeypatch.setitem(
        CANDIDATES, "Steel-toe work boots", [Candidate("x", "Steel Toe Boot", "sketchy.shop", D("99"), "https://x")]
    )
    fund("Steel-toe work boots")
    p = client.get("/households/me/purchases", headers=login_as("Elena Rivera")).json()[0]
    assert p["status"] == "blocked" and fakes == []
    assert [c["rule"] for c in p["policy_checks"] if not c["passed"]] == ["known_retailer"]


def test_reject_and_payout_failure(fakes, monkeypatch):
    fund("Twin mattresses")
    h = login_as("Elena Rivera")
    p = client.get("/households/me/purchases", headers=h).json()[0]
    assert client.post(f"/purchases/{p['id']}/reject", headers=h).json()["status"] == "rejected"

    def boom(*args, **kwargs):
        raise RuntimeError("PayPal down")

    monkeypatch.setattr(payouts, "send_payouts", boom)
    with SessionLocal() as db:
        item = db.query(RegistryItem).filter_by(name="Twin mattresses").one()
        purchase = shopping.plan_purchase(db, item)
        assert purchase.status == "awaiting_approval"
        failed = shopping.execute(db, purchase)
        assert failed.status == "failed" and "PayPal down" in failed.error
        assert ledger.household_available(db, item.rebuild_registry.household_id) == D("498.00")  # nothing spent


def test_shipping_simulation_marks_item_delivered(fakes):
    item_id = fund("Steel-toe work boots")
    h = login_as("Elena Rivera")
    pid = client.get("/households/me/purchases", headers=h).json()[0]["id"]
    shipped = client.post(f"/purchases/{pid}/simulate-shipping", headers=h).json()
    assert shipped["status"] == "shipped" and shipped["tracking_number"].startswith("1Z")
    assert client.post(f"/purchases/{pid}/simulate-shipping", headers=h).json()["status"] == "delivered"
    with SessionLocal() as db:
        assert db.get(RegistryItem, item_id).status == "delivered"
        assert db.query(Purchase).count() == 1
