from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app import audit, ledger
from app.agents import policy_agent
from app.db import SessionLocal
from app.models import AuditEvent, Household, InsuranceClaim, Item, Media
from app.paypal import orders, payouts
from app.paypal.orders import Capture
from app.paypal.webhooks import handle
from app.seed_inventory import seed_rivera_inventory
from scripts import sample_policy
from tests.helpers import client, login_as
from tests.paypal_stub import TRANSACTIONS_PATH, json_response, transaction, transactions_body
from tests.test_insurance import READ, upload


@pytest.fixture
def paypal(monkeypatch):
    """Fake PayPal: the insurer's order and capture (fee 3.49% + $0.49), and payouts to the household."""
    calls = {"orders": [], "payouts": []}

    def create_order(*, amount, description, custom_id, reference_id):
        calls["orders"].append((custom_id, amount))
        return f"ORDER-{len(calls['orders'])}"

    def capture_order(order_id):
        custom_id, amount = calls["orders"][int(order_id.split("-")[1]) - 1]
        fee = (amount * D("0.0349") + D("0.49")).quantize(D("0.01"))
        return Capture(order_id, f"CAP{order_id[-1]}0000000000000", "COMPLETED", amount, fee, "paypal")

    def send(payments, batch_id, subject):
        calls["payouts"].append(payments[0])
        return payouts.PayoutResult(batch_id=batch_id, status="PENDING")

    monkeypatch.setattr(orders, "create_order", create_order)
    monkeypatch.setattr(orders, "capture_order", capture_order)
    monkeypatch.setattr(payouts, "send_payouts", send)
    return calls


@pytest.fixture
def elena(monkeypatch):
    monkeypatch.setattr(policy_agent, "read", lambda text: READ)
    headers = login_as("Elena Rivera")
    with SessionLocal() as db:
        seed_rivera_inventory(db)
        home = db.query(Household).filter_by(name="Rivera household").one()
        home.payout_email = "elena.rivera@personal.example.com"  # her PayPal account (Log in with PayPal)
        photo = Media(household_id=home.id, content_type="image/jpeg", data=b"jpeg", width=1, height=1, sha256="x" * 64)
        db.add(photo)
        db.flush()
        piano = db.query(Item).filter_by(household_id=home.id, name="Upright piano").one()
        piano.media_id = photo.id
        db.commit()
    assert upload(headers, sample_policy.build()).status_code == 201
    return headers


def household():
    with SessionLocal() as db:
        return db.query(Household).filter_by(name="Rivera household").one()


def test_the_claim_follows_the_inventory_and_the_policy(elena):
    assert client.get("/households/me/claim", headers=elena).json() is None
    claim = client.post("/households/me/claim", headers=elena).json()
    inventory = D(claim["inventory_value"])
    # Jewelry is $2,650 over its $2,500 sub-limit; then the $2,500 deductible.
    assert D(claim["estimate"]) == inventory - D("2650.00") - D("2500.00")
    assert claim["status"] == "submitted" and claim["link"].endswith(claim["link"].rsplit("/", 1)[1])

    token = claim["link"].rsplit("/", 1)[1]
    packet = client.get(f"/claims/{token}").json()
    assert packet["insurer"].startswith("Golden Poppy") and packet["policy_number"] == "GPM-HO3-4471-2026"
    assert packet["policyholder"] == "Rivera household" and "Sablewood" in packet["address"]
    assert len(packet["items"]) == claim["items"] and D(packet["inventory_value"]) == inventory
    jewelry = [i for i in packet["items"] if i["sub_limit"]]
    assert {i["name"] for i in jewelry} == {"Gold wedding band and diamond necklace", "Grandmother's pearl earrings"}
    assert packet["sub_limits"][0]["over_by"] == "2650.00"
    piano = next(i for i in packet["items"] if i["name"] == "Upright piano")
    assert piano["photo_url"].startswith("/media/") and "?t=" in piano["photo_url"]  # a signed link to the photo
    assert piano["evidence"] == "pre_disaster_scan" and piano["recorded_at"]
    assert client.get("/claims/not-a-real-token").status_code == 404

    again = client.post("/households/me/claim", headers=elena).json()
    assert again["id"] == claim["id"] and again["link"] == claim["link"]  # rebuilt in place, same link


def test_the_adjuster_pays_and_the_money_goes_on_to_the_family(elena, paypal):
    claim = client.post("/households/me/claim", headers=elena).json()
    token = claim["link"].rsplit("/", 1)[1]
    amount = claim["estimate"]  # the adjuster pays what the policy's limits suggest
    r = client.post(f"/claims/{token}/order", json={"amount": amount, "adjuster_name": "Dana Lee", "note": "Approved"})
    assert r.json() == {"order_id": "ORDER-1"} and paypal["orders"] == [(f"claim:{claim['id']}", D(amount))]

    paid = client.post(f"/claims/{token}/capture").json()
    assert (paid["status"], paid["approved_amount"], paid["payout_status"]) == ("paid", amount, "sent")
    home = household()
    assert paypal["payouts"] == [
        (
            home.payout_email,
            D(amount),
            "Insurance claim payment from Golden Poppy Mutual Insurance Company",
            f"claim-{claim['id']}",
        )
    ]
    with SessionLocal() as db:
        assert ledger.household_available(db, home.id) == D(0)  # in, and straight back out to their PayPal
        kinds = [r["kind"] for r in client.get("/households/me/ledger", headers=elena).json()]
        assert kinds[:2] == ["claim_payout", "insurance_payment"]
        assert db.query(AuditEvent).filter_by(action="claim.approved_by_adjuster").one().data["adjuster"] == "Dana Lee"

    status = client.get("/households/me/claim", headers=elena).json()
    assert status["paid_at"] and status["adjuster_name"] == "Dana Lee"
    assert client.post(f"/claims/{token}/capture").json()["status"] == "paid" and len(paypal["payouts"]) == 1
    assert client.post(f"/claims/{token}/order", json={"amount": "10", "adjuster_name": "Dana Lee"}).status_code == 409
    assert client.post("/households/me/claim", headers=elena).status_code == 409  # a paid claim stays as it was


def test_without_a_paypal_account_the_money_waits_in_the_family_fund(elena, paypal):
    with SessionLocal() as db:
        db.query(Household).filter_by(name="Rivera household").update({"payout_email": None})
        db.commit()
    token = client.post("/households/me/claim", headers=elena).json()["link"].rsplit("/", 1)[1]
    client.post(f"/claims/{token}/order", json={"amount": "500", "adjuster_name": "Dana Lee"})
    assert client.post(f"/claims/{token}/capture").json()["payout_status"] == "held"
    assert paypal["payouts"] == []
    with SessionLocal() as db:
        assert ledger.household_available(db, household().id) == D("500.00")


def test_the_adjuster_decides_within_what_was_claimed(elena, paypal):
    claim = client.post("/households/me/claim", headers=elena).json()
    token = claim["link"].rsplit("/", 1)[1]
    too_much = str(D(claim["inventory_value"]) + 1)
    assert (
        client.post(f"/claims/{token}/order", json={"amount": too_much, "adjuster_name": "Dana Lee"}).status_code == 400
    )
    assert client.post(f"/claims/{token}/order", json={"amount": "0", "adjuster_name": "Dana Lee"}).status_code == 422
    assert client.post(f"/claims/{token}/capture").status_code == 409  # nothing to capture yet
    assert paypal["orders"] == []


def test_the_webhook_completes_a_payment_the_page_didnt(elena, paypal):
    claim = client.post("/households/me/claim", headers=elena).json()
    token = claim["link"].rsplit("/", 1)[1]
    client.post(f"/claims/{token}/order", json={"amount": "750", "adjuster_name": "Dana Lee"})
    resource = {
        "id": "CAPWEBHOOK0000001",
        "status": "COMPLETED",
        "custom_id": f"claim:{claim['id']}",
        "amount": {"currency_code": "USD", "value": "750.00"},
        "seller_receivable_breakdown": {"paypal_fee": {"currency_code": "USD", "value": "26.67"}},
    }
    with SessionLocal() as db:
        handle(db, {"id": "WH-CLAIM-1", "event_type": "PAYMENT.CAPTURE.COMPLETED", "resource": resource}, verified=True)
        stored = db.get(InsuranceClaim, claim["id"])
        assert (stored.status, stored.paypal_capture_id, stored.payout_status) == ("paid", "CAPWEBHOOK0000001", "sent")


def test_books_match_the_insurer_payment_and_the_payout(elena, paypal, paypal_reporting):
    with SessionLocal() as db:
        audit.record(db, action="demo.seeded", subject_type="demo", subject_id="test")
        db.query(AuditEvent).filter_by(action="demo.seeded").update(
            {"created_at": datetime.now(UTC) - timedelta(days=1)}
        )
        db.commit()
    claim = client.post("/households/me/claim", headers=elena).json()
    token = claim["link"].rsplit("/", 1)[1]
    client.post(f"/claims/{token}/order", json={"amount": "1200", "adjuster_name": "Dana Lee"})
    client.post(f"/claims/{token}/capture")
    at = (datetime.now(UTC) - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    paypal_reporting.routes[TRANSACTIONS_PATH] = json_response(
        200,
        transactions_body(
            [
                transaction("CAP10000000000000", "T0006", "1200.00", at, custom=f"claim:{claim['id']}"),
                transaction("PAYOUTCLAIM000001", "T0001", "-1200.00", at, custom=f"claim-{claim['id']}"),
            ],
            refreshed=(datetime.now(UTC) + timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    body = client.get("/command/books/reconcile", headers=login_as("Sam Whitfield")).json()
    statuses = {line["paypal_id"]: line["status"] for line in body["lines"]}
    assert statuses == {"CAP10000000000000": "matched", "PAYOUTCLAIM000001": "matched"}
