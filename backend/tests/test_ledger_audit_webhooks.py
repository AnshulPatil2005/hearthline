from decimal import Decimal

import pytest

from app import audit, ledger
from app.db import SessionLocal
from app.models import AuditEvent, Household
from app.paypal import webhooks
from tests.helpers import client, login_as

D = Decimal


def rivera_id() -> int:
    login_as("Elena Rivera")
    with SessionLocal() as db:
        return db.query(Household).filter_by(name="Rivera household").one().id


def test_donation_then_purchase_keeps_books_balanced():
    hid = rivera_id()
    with SessionLocal() as db:
        ledger.record_donation(
            db,
            household_id=hid,
            gross=D("50.00"),
            fee=D("2.09"),
            capture_id="CAP-1",
            description="Donation for twin bed",
            meta={"registry_item_id": 1},
        )
        ledger.record_spend(
            db,
            kind="purchase",
            household_id=hid,
            amount=D("30.00"),
            paypal_ref="ORD-1",
            description="Twin sheet set",
            meta={},
        )
        db.commit()
        assert ledger.household_available(db, hid) == D("20.00")
        assert ledger.balance(db, ledger.CASH) == D("17.91")  # 50 - 2.09 fee - 30 spent
        assert ledger.balance(db, ledger.FEES) == D("2.09")
        # Across all accounts the ledger sums to zero.
        total = sum(ledger.balance(db, c) for c in (ledger.CASH, ledger.FEES, ledger.household_fund(hid)))
        assert total == 0


def test_posting_is_idempotent_and_must_balance():
    hid = rivera_id()
    with SessionLocal() as db:
        first = ledger.record_donation(
            db, household_id=hid, gross=D("10"), fee=D("0.5"), capture_id="CAP-2", description="x", meta={}
        )
        again = ledger.record_donation(
            db, household_id=hid, gross=D("10"), fee=D("0.5"), capture_id="CAP-2", description="x", meta={}
        )
        assert first.id == again.id
        with pytest.raises(ledger.UnbalancedTransaction):
            ledger.post(db, kind="adjustment", description="bad", lines={ledger.CASH: D("5")})


def test_audit_chain_detects_tampering():
    with SessionLocal() as db:
        for i in range(3):
            audit.record(db, action="test.event", subject_type="thing", subject_id=i, data={"amount": D("1.50") * i})
        db.commit()
        assert audit.verify_chain(db) == (True, None)
        second = db.query(AuditEvent).order_by(AuditEvent.id).all()[1]
        second.data = {"amount": "999"}
        db.commit()
        assert audit.verify_chain(db) == (False, second.id)


EVENT = {"id": "WH-1", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": {"id": "CAP-9"}}


def test_webhook_is_processed_once(monkeypatch):
    calls = []
    monkeypatch.setitem(webhooks.HANDLERS, "PAYMENT.CAPTURE.COMPLETED", [lambda db, res: calls.append(res["id"])])

    async def ok(headers, event):
        return True

    monkeypatch.setattr(webhooks, "verify_signature", ok)
    assert client.post("/webhooks/paypal", json=EVENT).json() == {"received": "WH-1", "verified": True}
    client.post("/webhooks/paypal", json=EVENT)  # PayPal retry
    assert calls == ["CAP-9"]


def test_unverified_webhook_is_stored_but_not_processed(monkeypatch):
    calls = []
    monkeypatch.setitem(webhooks.HANDLERS, "PAYMENT.CAPTURE.COMPLETED", [lambda db, res: calls.append(1)])
    r = client.post("/webhooks/paypal", json=EVENT)  # no PAYPAL_WEBHOOK_ID / signature headers in tests
    assert r.json()["verified"] is False and calls == []
    assert client.post("/webhooks/paypal", json={"nope": 1}).status_code == 400
