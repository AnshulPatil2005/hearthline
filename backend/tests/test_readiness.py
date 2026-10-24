"""The readiness fund: monthly gifts through PayPal Subscriptions (stubbed here) are credited to the fund once each,
and first-72-hours aid draws on it, the rest coming from general cash aid."""

from decimal import Decimal as D

import pytest

from app import ledger, readiness
from app.db import SessionLocal
from app.models import AidBatch, LedgerAccount, ReadinessGiver, ReadinessPlan, User
from app.paypal import subscriptions
from tests.helpers import client, login_as
from tests.test_rapid_aid import fire_id, household, paid  # noqa: F401 - `paid` is a fixture


@pytest.fixture
def paypal(monkeypatch):
    """PayPal's Subscriptions API as it answers: plans, a subscription to approve, its status and payments."""
    calls = {"plans": 0, "subscriptions": 0, "cancelled": [], "status": "ACTIVE", "payments": []}

    def create_plan(**kwargs):
        calls["plans"] += 1
        assert kwargs["months"] == 0  # until the giver stops
        return f"P-{calls['plans']}"

    def subscribe(**kwargs):
        assert kwargs["custom_id"].startswith(readiness.CUSTOM_PREFIX)
        calls["subscriptions"] += 1
        sub_id = f"I-SUB{calls['subscriptions']}"
        return subscriptions.NewSubscription(id=sub_id, approval_url="https://paypal.test/approve", status="PENDING")

    monkeypatch.setattr(subscriptions, "create_plan", create_plan)
    monkeypatch.setattr(subscriptions, "subscribe", subscribe)
    monkeypatch.setattr(subscriptions, "status", lambda _id: calls["status"])
    monkeypatch.setattr(subscriptions, "payments", lambda _id: calls["payments"])
    monkeypatch.setattr(subscriptions, "cancel", lambda sub_id, reason: calls["cancelled"].append(sub_id))
    return calls


def balance() -> D:
    with SessionLocal() as db:
        return readiness.pool(db).balance


def test_a_monthly_gift_is_credited_to_the_fund_once(paypal):
    marcus = login_as("Marcus Chen")
    assert client.post("/donors/me/readiness", json={"monthly": "7"}, headers=marcus).status_code == 409
    started = client.post("/donors/me/readiness", json={"monthly": "25"}, headers=marcus)
    assert started.status_code == 201, started.text
    assert started.json()["approval_url"] == "https://paypal.test/approve"
    giver_id = started.json()["giver"]["id"]
    assert client.get("/donors/me/readiness", headers=marcus).json()["mine"]["status"] == "pending"

    paypal["payments"] = [("SALE-1", D("25.00"), D("1.03"))]
    back = client.post(f"/donors/me/readiness/{giver_id}/finish", headers=marcus).json()
    assert (back["mine"]["status"], back["mine"]["given"], back["pool"]["givers"]) == ("active", "25.00", 1)
    client.post(f"/donors/me/readiness/{giver_id}/finish", headers=marcus)  # back again: no second credit
    with SessionLocal() as db:  # the webhook for the same sale changes nothing either
        readiness.on_sale_completed(
            db, {"id": "SALE-1", "billing_agreement_id": "I-SUB1", "amount": {"total": "25.00"}}
        )
        readiness.on_sale_completed(  # next month's payment arrives by webhook
            db,
            {
                "id": "SALE-2",
                "billing_agreement_id": "I-SUB1",
                "amount": {"total": "25.00"},
                "transaction_fee": {"value": "1.03"},
            },
        )
        assert ledger.balance(db, ledger.FEES) == D("2.06")
        assert db.query(LedgerAccount).filter_by(code=readiness.FUND).one().kind == "liability"
    assert balance() == D("50.00")
    assert client.get("/readiness").json()["balance"] == "50.00"  # public

    assert client.post("/donors/me/readiness", json={"monthly": "10"}, headers=marcus).status_code == 409
    stopped = client.post(f"/donors/me/readiness/{giver_id}/stop", headers=marcus).json()
    assert stopped["mine"] is None and paypal["cancelled"] == ["I-SUB1"]
    assert client.post(f"/donors/me/readiness/{giver_id}/stop", headers=marcus).status_code == 409
    elena = login_as("Elena Rivera")
    assert client.post("/donors/me/readiness", json={"monthly": "10"}, headers=elena).status_code == 403


def test_a_gift_nobody_approved_stops_without_asking_paypal_to_cancel(paypal):
    marcus = login_as("Marcus Chen")
    giver_id = client.post("/donors/me/readiness", json={"monthly": "10"}, headers=marcus).json()["giver"]["id"]
    paypal["status"] = "APPROVAL_PENDING"
    assert client.post(f"/donors/me/readiness/{giver_id}/stop", headers=marcus).json()["mine"] is None
    assert paypal["cancelled"] == []


def test_the_plan_for_an_amount_is_made_once(paypal):
    login_as("Marcus Chen")  # seeds the scenario
    with SessionLocal() as db:
        marcus = db.query(User).filter_by(name="Marcus Chen").one()
        first, _ = readiness.start(db, marcus, D("25"), "https://web.test/giving/readiness")
        first.status = "cancelled"
        db.commit()
        readiness.start(db, marcus, D("25"), "https://web.test/giving/readiness")
        assert paypal["plans"] == 1 and db.query(ReadinessPlan).count() == 1


def test_first_72_hours_aid_draws_on_the_fund(paid):  # noqa: F811
    sam = login_as("Sam Whitfield")
    household("Ito household", level=3, email="ito@personal.example.com", size=4)  # $400
    household("Nguyen household", level=3, email="nguyen@personal.example.com")  # $250
    with SessionLocal() as db:
        giver = ReadinessGiver(name="Ana G.", monthly=D("50"), status="active")
        db.add(giver)
        db.flush()
        readiness.record_payment(db, giver, "SALE-A", D("500.00"), D("0"))

    board = client.post("/command/rapid-aid/simulate", json={"disaster_id": fire_id()}, headers=sam).json()
    assert board["readiness"] == {"balance": "500.00", "givers": 1, "monthly": "50.00"}
    proposal = board["triggers"][0]
    assert (proposal["total"], proposal["readiness_covers"]) == ("650.00", "500.00")

    board = client.post(f"/command/rapid-aid/{proposal['id']}/approve", headers=sam).json()
    assert board["triggers"][0]["readiness_covers"] == "500.00" and board["readiness"]["balance"] == "0.00"
    with SessionLocal() as db:
        batch = db.get(AidBatch, board["triggers"][0]["batch"]["id"])
        assert batch.rule["readiness_covered"] == "500.00"
        assert readiness.release(db, batch, batch.created_by) == D("500.00")  # a retry releases nothing more
        assert readiness.pool(db).released == D("500.00") and readiness.pool(db).balance == D("0.00")
