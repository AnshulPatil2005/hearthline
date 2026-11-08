from decimal import Decimal as D

import pytest

from app import audit, ledger, registry, shopping
from app.agents import shopper
from app.agents.shopper import Candidate, ShopperChoice
from app.db import SessionLocal
from app.models import Donation, Household, Purchase, RegistryItem
from app.paypal import payouts
from app.paypal.orders import Capture
from app.paypal.rest import PayPalError
from tests.helpers import client, login_as

REAL_CHOOSE = shopper.choose  # before the fixture swaps in a fake

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


def fund(item_name: str, *, proven: bool = True) -> int:
    """Fully fund a registry item through the real capture path; returns the item id. The Riveras' utility bill
    was checked at the shelter (as in the demo) unless `proven` is False."""
    login_as("Elena Rivera")
    with SessionLocal() as db:
        db.query(Household).filter_by(name="Rivera household").one().residence_verified = proven
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
    assert all(c["passed"] for c in p["policy_checks"]) and len(p["policy_checks"]) == 9  # 8 + the gouging guard
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


def test_without_the_ai_the_family_approves_the_cheapest_offer(fakes, monkeypatch):
    from app import ai

    def no_model(*args, **kwargs):
        raise ai.AIError("No AI model could answer: none configured")

    monkeypatch.setattr(shopper, "choose", REAL_CHOOSE)
    monkeypatch.setattr(ai, "parse", no_model)
    fund("Steel-toe work boots")
    p = client.get("/households/me/purchases", headers=login_as("Elena Rivera")).json()[0]
    assert p["status"] == "awaiting_approval" and fakes == []  # nothing paid on a guess
    assert p["retailer"] == "walmart.com" and p["total"] == "89.00"  # the cheapest offer within budget
    assert p["ai_reasoning"] == shopper.NO_AI_REASON


def test_nothing_ships_to_an_address_nobody_proved(fakes):
    """Inside the fire zone isn't enough: until a document or a caseworker confirms the family lives there, the
    Shopper won't send anything to it."""
    fund("Steel-toe work boots", proven=False)
    p = client.get("/households/me/purchases", headers=login_as("Elena Rivera")).json()[0]
    assert p["status"] == "blocked" and fakes == []
    assert [c["rule"] for c in p["policy_checks"] if not c["passed"]] == ["ships_to_verified_address"]


def test_a_second_shop_for_the_same_item_is_refused(fakes):
    """Two purchases for one item could both be approved and paid."""
    fund("Twin mattresses")  # $458: waits for the family's approval
    h = login_as("Elena Rivera")
    waiting = client.get("/households/me/purchases", headers=h).json()[0]
    again = client.post(f"/households/me/registry/items/{waiting['registry_item_id']}/shop", headers=h)
    assert again.status_code == 409 and "already buying" in again.json()["detail"]
    assert len(client.get("/households/me/purchases", headers=h).json()) == 1


def test_an_approval_checks_again_what_changed_since_the_proposal(fakes):
    fund("Twin mattresses")
    h = login_as("Elena Rivera")
    waiting = client.get("/households/me/purchases", headers=h).json()[0]
    with SessionLocal() as db:  # meanwhile the family's money was spent on something else
        home = db.query(Household).filter_by(name="Rivera household").one()
        ledger.record_spend(
            db,
            kind="purchase",
            household_id=home.id,
            amount=ledger.household_available(db, home.id),
            paypal_ref="ELSEWHERE-1",
            description="Spent elsewhere",
            meta={},
        )
        db.commit()
    r = client.post(f"/purchases/{waiting['id']}/approve", headers=h)
    assert r.status_code == 409 and "enough money" in r.json()["detail"] and fakes == []


def test_reject_and_payout_failure(fakes, monkeypatch):
    fund("Twin mattresses")
    h = login_as("Elena Rivera")
    p = client.get("/households/me/purchases", headers=h).json()[0]
    assert client.post(f"/purchases/{p['id']}/reject", headers=h).json()["status"] == "rejected"

    def refused(*args, **kwargs):
        raise PayPalError(422, {"name": "RECEIVER_UNREGISTERED", "message": "PayPal down"})

    monkeypatch.setattr(payouts, "send_payouts", refused)
    with SessionLocal() as db:
        item = db.query(RegistryItem).filter_by(name="Twin mattresses").one()
        purchase = shopping.plan_purchase(db, item)
        assert purchase.status == "awaiting_approval"
        failed = shopping.execute(db, purchase)
        assert failed.status == "failed" and "PayPal down" in failed.error
        assert ledger.household_available(db, item.rebuild_registry.household_id) == D("498.00")  # nothing spent


def test_a_payout_with_no_answer_waits_and_a_retry_pays_once(fakes, monkeypatch):
    """A timeout can come after PayPal paid. Marked failed, the family's next try was a new purchase with a new batch
    id that PayPal would pay again; instead the same purchase waits, and approving it resends the same batch."""
    import httpx

    fund("Twin mattresses")
    h = login_as("Elena Rivera")
    waiting = client.get("/households/me/purchases", headers=h).json()[0]
    real = payouts.send_payouts

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("no answer")

    monkeypatch.setattr(payouts, "send_payouts", timeout)
    unknown = client.post(f"/purchases/{waiting['id']}/approve", headers=h).json()
    assert unknown["status"] == "awaiting_approval" and "can't be paid twice" in unknown["error"]
    again = client.post(f"/households/me/registry/items/{waiting['registry_item_id']}/shop", headers=h)
    assert again.status_code == 409  # no second purchase for the same item
    monkeypatch.setattr(payouts, "send_payouts", real)
    paid = client.post(f"/purchases/{waiting['id']}/approve", headers=h).json()
    assert paid["status"] == "paid" and len(fakes) == 1


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


def test_household_ledger_shows_running_balance(fakes):
    fund("Steel-toe work boots")
    rows = client.get("/households/me/ledger", headers=login_as("Elena Rivera")).json()
    assert [(r["kind"], r["amount"], r["balance"]) for r in rows] == [
        ("purchase", "-129.99", "9.01"),
        ("donation", "139.00", "139.00"),
    ]
    postings = {
        p["account_code"].rsplit(":", 1)[0] if "household" in p["account_code"] else p["account_code"]: p["amount"]
        for p in rows[1]["postings"]
    }
    assert postings == {"assets:paypal": "136.00", "expenses:paypal_fees": "3.00", "liabilities:household": "-139.00"}


def test_shipping_puts_the_tracking_number_on_donors_paypal_payments(fakes, no_live_tracking):
    fund("Steel-toe work boots")
    h = login_as("Elena Rivera")
    p = client.get("/households/me/purchases", headers=h).json()[0]
    shipped = client.post(f"/purchases/{p['id']}/simulate-shipping", headers=h).json()
    with SessionLocal() as db:
        item = db.query(RegistryItem).filter_by(name="Steel-toe work boots").one()
    assert no_live_tracking == [(f"O-{item.id}", f"CAP-{item.id}", shipped["tracking_number"])]


def test_the_per_unit_budget_never_rounds_above_what_was_given():
    per_unit = shopping.unit_budget(D("100.01"), 3)
    assert per_unit == D("33.33") and per_unit * 3 <= D("100.01")
