from decimal import Decimal as D

import pytest

from app import aid_batches, ledger, seed_command
from app.db import SessionLocal
from app.models import AidBatch, Household
from app.paypal import payouts, webhooks
from app.paypal.rest import PayPalError
from tests.helpers import client, login_as

DESTROYED_VERIFIED = {
    "damage_level": {"filterType": "set", "values": ["destroyed"]},
    "verification_level": {"filterType": "set", "values": ["2"]},
}


@pytest.fixture
def town(monkeypatch):
    sent = []

    def send(payments, batch_id, subject):
        sent.append(payments)
        return payouts.PayoutResult(batch_id=f"PAYPAL-{batch_id}", status="PENDING")

    monkeypatch.setattr(payouts, "send_payouts", send)
    sam = login_as("Sam Whitfield")
    monkeypatch.setattr(seed_command, "COUNT", 120)
    with SessionLocal() as db:
        seed_command.seed_command_center(db)
    return sam, login_as("Grace Alvarez"), sent


def preview(headers, **body):
    r = client.post("/command/batches/preview", headers=headers, json={"filter_model": DESTROYED_VERIFIED, **body})
    assert r.status_code == 200, r.text
    return r.json()


def create(headers, title="Destroyed homes, wave 2", **body):
    r = client.post(
        "/command/batches", headers=headers, json={"title": title, "filter_model": DESTROYED_VERIFIED, **body}
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_preview_accounts_for_every_household_in_the_view(town):
    sam, _, _ = town
    view = client.post(
        "/command/households/rows", headers=sam, json={"filterModel": DESTROYED_VERIFIED, "startRow": 0, "endRow": 1}
    ).json()
    p = preview(sam)
    assert p["households"] + sum(p["excluded"].values()) == view["matching"]
    assert p["households"] > 0 and set(p["by_damage"]) == {"destroyed"}
    assert D(p["total"]) <= p["households"] * D(1000)  # never more than the destroyed-home amount


def test_two_people_pay_a_batch_and_the_books_follow(town):
    sam, grace, sent = town
    batch = create(sam)
    assert batch["status"] == "awaiting_approval" and batch["can_decide"] is False
    refused = client.post(f"/command/batches/{batch['id']}/approve", headers=sam)
    assert refused.status_code == 409 and "second person" in refused.json()["detail"]
    assert sent == []

    approved = client.post(f"/command/batches/{batch['id']}/approve", headers=grace).json()
    assert approved["status"] == "sent" and approved["decided_by"] == "Grace Alvarez"
    assert len(sent) == 1 and len(sent[0]) == approved["households"]
    assert approved["status_counts"] == {"PENDING": approved["households"]}

    with SessionLocal() as db:
        paid_to = [i.household_id for i in db.get(AidBatch, batch["id"]).items]
    first = client.post(
        "/command/households/rows",
        headers=sam,
        json={
            "filterModel": {"name": {"filterType": "text", "type": "contains", "filter": ""}},
            "startRow": 0,
            "endRow": 500,
        },
    ).json()["rows"]
    helped = {r["id"]: D(r["help_received"]) for r in first}
    assert all(helped[h] >= D(25) for h in paid_to)
    # Everyone just paid is now left out of the next batch.
    again = preview(sam)
    assert again["households"] == 0 or again["excluded"]["recent_aid"] >= len(paid_to)


def test_households_in_a_waiting_batch_are_not_put_in_another(town):
    sam, _, _ = town
    first = create(sam)
    p = preview(sam)
    assert p["households"] == 0 and p["excluded"]["in_open_batch"] == first["households"]
    r = client.post("/command/batches", headers=sam, json={"title": "Duplicate", "filter_model": DESTROYED_VERIFIED})
    assert r.status_code == 409


def test_amount_never_exceeds_what_is_still_needed_and_shared_paypal_is_left_out(town):
    sam, _, _ = town
    with SessionLocal() as db:
        homes = db.query(Household).filter_by(damage_level="destroyed", verification_level=2).limit(3).all()
        homes[0].estimated_loss = D("300")  # only $300 still needed
        homes[1].payout_email = homes[2].payout_email = "same.person@personal.example.com"
        ids = [h.id for h in homes]
        db.commit()
    with SessionLocal() as db:
        chosen, excluded = aid_batches.plan(db, DESTROYED_VERIFIED, aid_batches.DEFAULT_AMOUNTS)
    by_id = {c.household_id: c for c in chosen}
    if ids[0] in by_id:  # unless it already got wave 1 aid recently
        assert by_id[ids[0]].amount <= D("300")
    assert ids[1] not in by_id and ids[2] not in by_id and excluded["shared_paypal"] >= 2


def test_a_low_balance_fails_the_batch_without_moving_money_and_it_can_be_retried(town, monkeypatch):
    sam, grace, sent = town
    batch = create(sam)
    real_send = payouts.send_payouts

    def broke(*a, **k):
        raise PayPalError(422, {"name": "INSUFFICIENT_FUNDS"})

    monkeypatch.setattr(payouts, "send_payouts", broke)
    failed = client.post(f"/command/batches/{batch['id']}/approve", headers=grace).json()
    assert failed["status"] == "failed" and "balance can't cover this batch" in failed["error"]
    with SessionLocal() as db:
        assert (
            db.query(ledger.LedgerTransaction).filter(ledger.LedgerTransaction.paypal_ref.like("aidbatch-%")).count()
            == 0
        )

    monkeypatch.setattr(payouts, "send_payouts", real_send)
    retried = client.post(f"/command/batches/{batch['id']}/approve", headers=grace).json()
    assert retried["status"] == "sent" and len(sent) == 1


def test_money_paypal_returns_goes_back_to_the_relief_fund(town):
    sam, grace, _ = town
    batch = create(sam)
    client.post(f"/command/batches/{batch['id']}/approve", headers=grace)
    with SessionLocal() as db:
        item = db.get(AidBatch, batch["id"]).items[0]
        sender_id, amount = item.sender_item_id, item.amount
        before = ledger.balance(db, ledger.CASH_AID)
    event = {
        "id": "WH-1",
        "event_type": "PAYMENT.PAYOUTS-ITEM.RETURNED",
        "resource": {
            "payout_item_id": "ITEM-1",
            "transaction_status": "RETURNED",
            "payout_item": {"sender_item_id": sender_id},
        },
    }
    with SessionLocal() as db:
        webhooks.handle(db, event, verified=True)
        webhooks.handle(db, {**event, "id": "WH-2"}, verified=True)  # a second delivery changes nothing more
        assert ledger.balance(db, ledger.CASH_AID) == before - amount
    items = {i["status"] for i in client.get("/command/batches", headers=sam).json()[0]["items"]}
    assert "RETURNED" in items


def test_reject_needs_a_second_person_and_a_reason(town):
    sam, grace, sent = town
    batch = create(sam)
    assert (
        client.post(f"/command/batches/{batch['id']}/reject", headers=sam, json={"reason": "Wrong amounts"}).status_code
        == 409
    )
    rejected = client.post(
        f"/command/batches/{batch['id']}/reject", headers=grace, json={"reason": "Amounts too low"}
    ).json()
    assert rejected["status"] == "rejected" and rejected["decision_note"] == "Amounts too low" and sent == []
    assert preview(sam)["households"] == batch["households"]  # they're free for a new batch


def test_reviewers_and_households_cannot_build_batches(town):
    for name in ("Priya Nair", "Elena Rivera"):
        assert client.post("/command/batches/preview", headers=login_as(name), json={}).status_code == 403
