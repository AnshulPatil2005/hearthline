from decimal import Decimal as D

import pytest

from app import audit, ledger, review
from app.agents import sentinel
from app.agents.sentinel import SentinelNote
from app.db import SessionLocal
from app.models import Case, Donation, Household, Registry, RegistryItem, Role, User
from app.paypal import orders, payouts
from tests.helpers import client, login_as


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    sent, refunds = [], []

    def send_payouts(payments, batch_id, subject):
        sent.append(payments)
        return payouts.PayoutResult(batch_id=f"BATCH-{len(sent)}", status="PENDING")

    monkeypatch.setattr(
        sentinel,
        "explain",
        lambda facts, flags: SentinelNote(
            summary="Checked by test Sentinel.", questions=["Can you show a utility bill?"], recommendation="approve"
        ),
    )
    monkeypatch.setattr(payouts, "send_payouts", send_payouts)
    monkeypatch.setattr(orders, "refund_capture", lambda capture_id: refunds.append(capture_id) or "COMPLETED")
    monkeypatch.setattr(review, "AUDIT_RATE", 0.0)  # random audits are tested on their own below
    return {"sent": sent, "refunds": refunds}


def assigned(case_id: int, role: str = Role.REVIEWER) -> list[str]:
    with SessionLocal() as db:
        return [a.reviewer.name for a in db.get(Case, case_id).assignments if a.role == role]


def set_payout_email(email="elena@personal.example.com", residence_verified=True):
    """Ready the Riveras for cash aid: a payout account and (by default) a confirmed residence (level 2)."""
    with SessionLocal() as db:
        home = db.query(Household).filter_by(name="Rivera household").one()
        home.payout_email = email
        home.residence_verified = residence_verified
        db.commit()


def test_low_risk_cash_aid_needs_one_human_then_pays(fakes):
    h = login_as("Elena Rivera")
    set_payout_email()
    case = client.post("/households/me/cases", headers=h, json={"kind": "cash_aid", "amount": "500"}).json()
    assert case["status"] == "in_review" and not case["video_call_required"]
    reviewers = assigned(case["id"])
    assert len(reviewers) == 1 and fakes["sent"] == []  # nothing paid before a human decides

    other = ({"Priya Nair", "Tom Becker"} - set(reviewers)).pop()
    blocked = client.post(f"/review/cases/{case['id']}/decision", headers=login_as(other), json={"decision": "approve"})
    assert blocked.status_code == 409  # not assigned to them

    detail = client.get(f"/review/cases/{case['id']}", headers=login_as(reviewers[0])).json()
    assert detail["sentinel_summary"] and detail["in_disaster_zone"] and detail["payout_email"].startswith("el***@")
    done = client.post(
        f"/review/cases/{case['id']}/decision", headers=login_as(reviewers[0]), json={"decision": "approve"}
    ).json()
    assert done["status"] == "approved"
    assert fakes["sent"][0][0][:2] == ("elena@personal.example.com", D("500.00"))
    with SessionLocal() as db:
        assert ledger.balance(db, ledger.CASH_AID) == D("500.00")
        assert audit.verify_chain(db) == (True, None)
    assert client.get("/households/me/cases", headers=h).json()[0]["status"] == "approved"


def test_large_cash_aid_needs_two_and_a_supervisor_on_disagreement(fakes):
    h = login_as("Elena Rivera")
    set_payout_email()
    case = client.post("/households/me/cases", headers=h, json={"kind": "cash_aid", "amount": "2000"}).json()
    first, second = assigned(case["id"])
    url = f"/review/cases/{case['id']}/decision"
    assert client.post(url, headers=login_as(first), json={"decision": "approve"}).json()["status"] == "in_review"
    escalated = client.post(
        url, headers=login_as(second), json={"decision": "reject", "reason": "Address unclear"}
    ).json()
    assert escalated["status"] == "escalated" and fakes["sent"] == []
    assert assigned(case["id"], Role.SUPERVISOR) == ["Grace Alvarez"]
    final = client.post(
        url, headers=login_as("Grace Alvarez"), json={"decision": "approve", "reason": "Vouched in person"}
    )
    assert final.json()["status"] == "approved" and len(fakes["sent"]) == 1


def test_request_info_then_household_reply(fakes):
    h = login_as("Elena Rivera")
    case = client.post("/households/me/cases", headers=h, json={"kind": "contents_claim"}).json()
    reviewer = login_as(assigned(case["id"])[0])
    url = f"/review/cases/{case['id']}/decision"
    assert client.post(url, headers=reviewer, json={"decision": "request_info"}).status_code == 409  # reason needed
    asked = client.post(
        url, headers=reviewer, json={"decision": "request_info", "reason": "Please add a receipt"}
    ).json()
    assert asked["status"] == "needs_info"
    mine = client.get("/households/me/cases", headers=h).json()[0]
    assert mine["decision_note"] == "Please add a receipt"
    assert (
        client.post(f"/households/me/cases/{case['id']}/reply", headers=h, json={"note": "Uploaded"}).json()["status"]
        == "in_review"
    )
    assert client.post(url, headers=reviewer, json={"decision": "approve"}).json()["status"] == "approved"


def test_households_cannot_use_staff_endpoints():
    h = login_as("Elena Rivera")
    case = client.post("/households/me/cases", headers=h, json={"kind": "contents_claim"}).json()
    assert client.get("/review/queue", headers=h).status_code == 403
    assert client.get(f"/review/cases/{case['id']}", headers=h).status_code == 403


def new_household(name: str, lat: float, lng: float, email: str) -> dict:
    """A second family with its own login, created directly in the database."""
    login_as("Elena Rivera")
    with SessionLocal() as db:
        fire = db.query(Household).filter_by(name="Rivera household").one().disaster_event
        home = Household(
            name=name,
            address_line="9 Pine St",
            city="Sablewood",
            state="CA",
            postal_code="95999",
            lat=lat,
            lng=lng,
            disaster_event=fire if lat < 38.75 else None,
        )
        user = User(email=email, name=name.split()[0] + " Test", role=Role.HOUSEHOLD, is_demo=True, household=home)
        db.add_all([home, user])
        db.commit()
        return {"user_id": user.id, "household_id": home.id}


def headers_for(user_id: int) -> dict:
    return {"Authorization": "Bearer " + client.post("/auth/demo-login", json={"user_id": user_id}).json()["token"]}


def test_new_registry_is_hidden_until_a_human_approves(fakes):
    ids = new_household("Nguyen household", 38.71, -120.63, "nguyen@demo.hearthline.app")
    h = headers_for(ids["user_id"])
    reg = client.post("/households/me/registry", headers=h, json={"title": "Help the Nguyens"}).json()
    assert reg["status"] == "pending_review"
    assert client.post(f"/registries/{reg['slug']}/donations", json={"amount": "10"}).status_code == 409
    assert client.get(f"/registries/{reg['slug']}").status_code == 404  # not public yet
    assert client.get(f"/registries/{reg['slug']}", headers=h).json()["status"] == "pending_review"  # the family
    assert client.get(f"/registries/{reg['slug']}", headers=login_as("Priya Nair")).status_code == 200  # a reviewer

    case = client.get("/households/me/cases", headers=h).json()[0]
    assert case["kind"] == "registry_verification"
    for name in assigned(case["id"]):
        client.post(f"/review/cases/{case['id']}/decision", headers=login_as(name), json={"decision": "approve"})
    assert client.get(f"/registries/{reg['slug']}").json()["status"] == "active"


def test_rejected_registry_refunds_every_donor(fakes):
    ids = new_household("Rivera family fund", 36.0, -115.0, "scam@demo.hearthline.app")  # outside the fire
    h = headers_for(ids["user_id"])
    reg = client.post("/households/me/registry", headers=h, json={"title": "Help the Riveras (copy)"}).json()
    with SessionLocal() as db:  # donations that came in before anyone noticed
        registry = db.query(Registry).filter_by(slug=reg["slug"]).one()
        registry.status = "active"
        item = RegistryItem(registry_id=registry.id, name="Laptop", unit_price=D("400"), funded_amount=D("150"))
        db.add(item)
        db.flush()
        for capture_id, amount in (("CAP-REAL-1", "100"), ("DEMO-2", "50")):
            db.add(
                Donation(
                    registry_id=registry.id,
                    registry_item_id=item.id,
                    amount=D(amount),
                    status="captured",
                    paypal_capture_id=capture_id,
                    paypal_order_id=f"O-{capture_id}",
                )
            )
            ledger.record_donation(
                db,
                household_id=registry.household_id,
                gross=D(amount),
                fee=D("0"),
                capture_id=capture_id,
                description="seed",
                meta={},
            )
        db.commit()

    case = client.get("/households/me/cases", headers=h).json()[0]
    detail_reviewers = assigned(case["id"])
    assert len(detail_reviewers) == 2  # outside the zone = high risk = two reviewers
    for name in detail_reviewers:
        client.post(
            f"/review/cases/{case['id']}/decision",
            headers=login_as(name),
            json={"decision": "reject", "reason": "Copied photos, address outside the fire"},
        )
    assert fakes["refunds"] == ["CAP-REAL-1"]  # DEMO- captures are seeded demo data, refunded without PayPal
    with SessionLocal() as db:
        registry = db.query(Registry).filter_by(slug=reg["slug"]).one()
        assert registry.status == "closed"
        assert {d.status for d in db.query(Donation).filter_by(registry_id=registry.id)} == {"refunded"}
        assert ledger.household_available(db, registry.household_id) == D("0.00")
        assert db.query(RegistryItem).filter_by(registry_id=registry.id).one().funded_amount == D("0.00")


def test_random_audit_never_blocks_an_approval(monkeypatch):
    monkeypatch.setattr(review, "AUDIT_RATE", 1.0)  # every approval gets audited
    h = login_as("Elena Rivera")
    set_payout_email()
    case = client.post("/households/me/cases", headers=h, json={"kind": "cash_aid", "amount": "2000"}).json()
    first, second = assigned(case["id"])
    url = f"/review/cases/{case['id']}/decision"
    client.post(url, headers=login_as(first), json={"decision": "approve"})
    client.post(url, headers=login_as(second), json={"decision": "reject", "reason": "Unsure about the address"})
    final = client.post(url, headers=login_as("Grace Alvarez"), json={"decision": "approve", "reason": "Confirmed"})
    assert final.json()["status"] == "approved"
    assert assigned(case["id"], "auditor") == ["Sam Whitfield"]  # Grace was involved, so the org admin audits


def test_cash_aid_cannot_be_approved_below_level_two(fakes):
    h = login_as("Elena Rivera")
    set_payout_email(residence_verified=False)  # level 1: inside the zone, residence not confirmed
    case = client.post("/households/me/cases", headers=h, json={"kind": "cash_aid", "amount": "300"}).json()
    reviewer = assigned(case["id"])[0]
    url = f"/review/cases/{case['id']}/decision"
    blocked = client.post(url, headers=login_as(reviewer), json={"decision": "approve"})
    assert blocked.status_code == 409 and "level 2" in blocked.json()["detail"] and fakes["sent"] == []

    with SessionLocal() as db:
        hid = db.query(Household).filter_by(name="Rivera household").one().id
    vouch = client.post(
        f"/trust/households/{hid}/vouch",
        headers=login_as("Sam Whitfield"),
        json={"note": "Known to the relief network since the shelter opened."},
    )
    assert vouch.json()["level"] == 2
    assert client.post(url, headers=login_as(reviewer), json={"decision": "approve"}).json()["status"] == "approved"
