"""First-72-hours aid: an official (or simulated) warning proposes aid; one person approves; prepared households in the
zone are paid in one PayPal Payouts batch; Sentinel holds back warning signs; donors' mandates get a round."""

from decimal import Decimal as D

import pytest

from app import rapid_aid
from app.db import SessionLocal
from app.models import AidBatch, DisasterEvent, EvidenceLevel, Household, Item, RapidAidTrigger
from app.paypal import payouts
from tests.helpers import client, login_as


@pytest.fixture
def paid(monkeypatch):
    sent = []

    def send_payouts(payments, batch_id, subject):
        sent.append(payments)
        return payouts.PayoutResult(batch_id=f"BATCH-{len(sent)}", status="PENDING")

    monkeypatch.setattr(payouts, "send_payouts", send_payouts)
    rounds = []
    monkeypatch.setattr(rapid_aid, "start_mandate_round", lambda: rounds.append(1))
    return sent, rounds


def household(name: str, *, level: int, email: str | None, size: int = 1, outlier: bool = False) -> int:
    """A household at the Riveras' address (inside the fire zone) at a given verification level."""
    with SessionLocal() as db:
        rivera = db.query(Household).filter_by(name="Rivera household").one()
        h = Household(
            name=name,
            address_line="1 Juniper Lane",
            city="Sablewood",
            state="CA",
            postal_code="95999",
            lat=rivera.lat,
            lng=rivera.lng,
            disaster_event_id=rivera.disaster_event_id,
            verification_level=level,
            residence_verified=level >= 2,
            payout_email=email,
            household_size=size,
        )
        db.add(h)
        db.flush()
        if outlier:
            db.add(
                Item(
                    household_id=h.id,
                    name="Television",
                    unit_price=D("9000"),
                    price_high=D("1200"),
                    evidence_level=EvidenceLevel.PRE_DISASTER_SCAN,
                )
            )
        db.commit()
        return h.id


def fire_id() -> int:
    with SessionLocal() as db:
        return db.query(DisasterEvent).filter_by(status="active").one().id


def test_one_person_approves_and_prepared_households_are_paid_in_one_batch(paid):
    sent, rounds = paid
    sam = login_as("Sam Whitfield")
    a = household("Ito household", level=3, email="ito@personal.example.com", size=4)
    b = household("Nguyen household", level=3, email="nguyen@personal.example.com", size=1)
    household("Park household", level=2, email="park@personal.example.com")  # verified, but no inventory on file
    household("Ruiz household", level=1, email="ruiz@personal.example.com")
    household("Shah household", level=3, email=None)  # prepared, but no PayPal account

    board = client.post("/command/rapid-aid/simulate", json={"disaster_id": fire_id()}, headers=sam).json()
    proposed = board["triggers"][0]
    assert (proposed["status"], proposed["source"], proposed["event"]) == ("proposed", "simulated", "Evacuation Order")
    assert (proposed["households"], proposed["total"]) == (2, "650.00")  # $250 + $50 × 3 others = $400, and $250
    assert proposed["left_out"]["not_prepared"] >= 1 and proposed["left_out"]["no_paypal"] == 1

    board = client.post(f"/command/rapid-aid/{proposed['id']}/approve", headers=sam).json()
    approved = board["triggers"][0]
    assert approved["status"] == "approved" and approved["decided_by"] == "Sam Whitfield"
    assert approved["batch"]["status"] == "sent" and approved["batch"]["households"] == 2
    assert sorted((p[0], p[1]) for p in sent[0]) == [
        ("ito@personal.example.com", D("400")),
        ("nguyen@personal.example.com", D("250")),
    ]
    with SessionLocal() as db:
        batch = db.get(AidBatch, approved["batch"]["id"])
        assert batch.created_by.email == rapid_aid.SYSTEM_EMAIL  # rules prepared it; Sam approved it
        assert {i.household_id for i in batch.items} == {a, b}
    assert rounds == [1]  # donors' giving mandates get a round for the new emergency
    again = client.post(f"/command/rapid-aid/{proposed['id']}/approve", headers=sam)
    assert again.status_code == 409


def test_sentinel_holds_back_a_household_with_warning_signs(paid):
    sent, _ = paid
    sam = login_as("Sam Whitfield")
    household("Ito household", level=3, email="ito@personal.example.com")
    flagged = household("Jackson household", level=3, email="jackson@personal.example.com", outlier=True)
    board = client.post("/command/rapid-aid/simulate", json={"disaster_id": fire_id()}, headers=sam).json()
    t = board["triggers"][0]
    assert t["households"] == 1
    assert [(h["household_id"], "twice the highest market price" in h["reason"]) for h in t["held"]] == [
        (flagged, True)
    ]
    board = client.post(f"/command/rapid-aid/{t['id']}/approve", headers=sam).json()
    assert [h["name"] for h in board["triggers"][0]["held"]] == ["Jackson household"]  # kept for the record
    assert [p[0] for p in sent[0]] == ["ito@personal.example.com"]


def test_an_official_warning_proposes_aid_once(paid, monkeypatch):
    sam = login_as("Sam Whitfield")
    household("Ito household", level=3, email="ito@personal.example.com")

    class Answer:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "features": [
                    {
                        "properties": {
                            "id": "urn:nws:1",
                            "event": "Evacuation Order",
                            "severity": "Extreme",
                            "headline": "Evacuation Order for Sablewood",
                            "sent": "2026-10-22T10:00:00-07:00",
                        }
                    },
                    {
                        "properties": {
                            "id": "urn:nws:2",
                            "event": "Heat Advisory",
                            "severity": "Moderate",
                            "headline": "Hot",
                        }
                    },
                ]
            }

    monkeypatch.setattr(rapid_aid.httpx, "get", lambda *a, **k: Answer())
    client.post("/command/rapid-aid/check", json={"disaster_id": fire_id()}, headers=sam)
    client.post("/command/rapid-aid/check", json={"disaster_id": fire_id()}, headers=sam)  # the same warning again
    with SessionLocal() as db:
        triggers = db.query(RapidAidTrigger).all()
        assert [(t.source, t.external_id, t.event) for t in triggers] == [("nws", "urn:nws:1", "Evacuation Order")]


def test_only_org_staff_and_a_dismissal_needs_a_reason(paid):
    sam = login_as("Sam Whitfield")
    board = client.post("/command/rapid-aid/simulate", json={"disaster_id": fire_id()}, headers=sam).json()
    trigger_id = board["triggers"][0]["id"]
    assert client.get("/command/rapid-aid", headers=login_as("Elena Rivera")).status_code == 403
    assert client.post(f"/command/rapid-aid/{trigger_id}/dismiss", json={"note": ""}, headers=sam).status_code == 422
    dismissed = client.post(
        f"/command/rapid-aid/{trigger_id}/dismiss", json={"note": "Order was lifted"}, headers=sam
    ).json()
    assert dismissed["triggers"][0]["status"] == "dismissed"
    assert client.post(f"/command/rapid-aid/{trigger_id}/approve", headers=sam).status_code == 409


def test_the_household_sees_first_72_hours_aid_on_its_aid_page(paid):
    elena = login_as("Elena Rivera")  # seeds the scenario
    with SessionLocal() as db:
        rivera = db.query(Household).filter_by(name="Rivera household").one()
        rivera.verification_level, rivera.residence_verified = 3, True
        rivera.payout_email, rivera.household_size = "elena@personal.example.com", 4
        db.commit()
    assert client.get("/households/me/batch-aid", headers=elena).json() == []
    sam = login_as("Sam Whitfield")
    board = client.post("/command/rapid-aid/simulate", json={"disaster_id": fire_id()}, headers=sam).json()
    client.post(f"/command/rapid-aid/{board['triggers'][0]['id']}/approve", headers=sam)
    [aid] = client.get("/households/me/batch-aid", headers=elena).json()
    assert (aid["amount"], aid["status"], aid["first_72_hours"]) == ("400.00", "PENDING", True)
    assert aid["receiver"] == "elena@personal.example.com"
