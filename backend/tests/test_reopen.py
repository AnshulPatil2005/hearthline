from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app import reopen
from app.db import SessionLocal
from app.models import Business, GiftCard, ReopenCampaign, User
from app.paypal import orders, payouts
from app.paypal.orders import Capture
from app.paypal.webhooks import handle
from tests.helpers import client, login_as

SOON = datetime.now(UTC) + timedelta(days=30)


@pytest.fixture
def paypal(monkeypatch):
    """Fake PayPal: orders, captures (fee 3.49% + $0.49), refunds and payouts are recorded, never sent."""
    calls = {"orders": [], "refunds": [], "payouts": []}

    def create_order(*, amount, description, custom_id, reference_id):
        calls["orders"].append((custom_id, amount))
        return f"ORDER-{len(calls['orders'])}"

    def capture_order(order_id):
        custom_id, amount = calls["orders"][int(order_id.split("-")[1]) - 1]
        fee = (amount * D("0.0349") + D("0.49")).quantize(D("0.01"))
        return Capture(order_id, f"CAP-{order_id}", "COMPLETED", amount, fee, "paypal")

    def send(payments, batch_id, subject):
        calls["payouts"].append(payments[0][:2])
        return payouts.PayoutResult(batch_id=f"PAYOUT-{len(calls['payouts'])}", status="PENDING")

    monkeypatch.setattr(orders, "create_order", create_order)
    monkeypatch.setattr(orders, "capture_order", capture_order)
    monkeypatch.setattr(
        orders, "refund_capture", lambda cid, amount=None: calls["refunds"].append((cid, amount)) or "COMPLETED"
    )
    monkeypatch.setattr(payouts, "send_payouts", send)
    return calls


@pytest.fixture
def luis():
    headers = login_as("Luis Moreno")
    with SessionLocal() as db:
        owner = db.query(User).filter_by(name="Luis Moreno").one()
        db.add(
            Business(
                owner_user_id=owner.id,
                name="Moreno's Bakery",
                slug="morenos-bakery",
                kind="bakery",
                address_line="120 Main St",
                city="Sablewood",
                state="CA",
                license_number="SBW-BL-20417",
                payout_email="luis.moreno@business.example.com",
            )
        )
        db.commit()
    return headers


def campaign_body(bonus=20):
    start = datetime.now(UTC)
    return {
        "bonus_percent": bonus,
        "reopen_by": SOON.isoformat(),
        "tranches": [
            {
                "title": "Replace the ovens",
                "amount": "700",
                "start_date": start.isoformat(),
                "end_date": (start + timedelta(days=10)).isoformat(),
            },
            {
                "title": "Restock supplies",
                "amount": "300",
                "start_date": (start + timedelta(days=10)).isoformat(),
                "end_date": (start + timedelta(days=20)).isoformat(),
            },
        ],
    }


def live_campaign(luis) -> dict:
    sam = login_as("Sam Whitfield")
    with SessionLocal() as db:
        bid = db.query(Business).one().id
    assert (
        client.post(
            f"/command/businesses/{bid}/verify", headers=sam, json={"approve": True, "note": "License checked"}
        ).status_code
        == 200
    )
    r = client.post("/business/me/campaign", headers=luis, json=campaign_body())
    assert r.status_code == 201, r.text
    return r.json()


def buy(amount: str, name="Ana") -> dict:
    started = client.post("/reopen/morenos-bakery/cards", json={"amount": amount, "buyer_name": name})
    assert started.status_code == 201, started.text
    s = started.json()
    return client.post(f"/gift-cards/{s['card_id']}/capture", params={"token": s["token"]}).json()


def test_only_a_verified_business_sells_cards_and_the_owner_cant_verify_itself(luis, paypal):
    assert client.post("/business/me/campaign", headers=luis, json=campaign_body()).status_code == 409
    with SessionLocal() as db:
        bid = db.query(Business).one().id
    assert client.post(f"/command/businesses/{bid}/verify", headers=luis, json={"approve": True}).status_code == 403
    assert client.post("/business/me/campaign", headers=luis, json=campaign_body(bonus=40)).status_code == 422
    biz = live_campaign(luis)
    assert biz["campaign"]["goal_amount"] == "1000.00" and biz["campaign"]["status"] == "live"
    assert client.post("/business/me/campaign", headers=luis, json=campaign_body()).status_code == 409  # one at a time


def test_buying_a_card_puts_the_money_in_escrow_with_the_bonus_on_the_card(luis, paypal):
    live_campaign(luis)
    card = buy("50")
    assert card["status"] == "active" and card["face_value"] == "60.00" and card["balance"] == "60.00"
    assert client.get(f"/gift-cards/{card['code'].lower()}").json()["balance"] == "60.00"  # codes aren't case-sensitive
    with SessionLocal() as db:
        c = db.query(ReopenCampaign).one()
        assert c.raised == D("50.00") and reopen.escrow_balance(db, c.id) == D("50.00")
        gift = db.query(GiftCard).filter_by(code=card["code"]).one()
        event = {
            "id": "WH-GC-1",
            "event_type": "PAYMENT.CAPTURE.COMPLETED",
            "resource": {
                "id": gift.paypal_capture_id,
                "status": "COMPLETED",
                "custom_id": f"giftcard:{gift.id}",
                "amount": {"value": "50.00"},
            },
        }
        handle(db, event, verified=True)  # the webhook arriving after our capture changes nothing
        assert db.query(ReopenCampaign).one().raised == D("50.00")
    buy("500")
    buy("400")  # $950 of the $1,000 goal
    over = client.post("/reopen/morenos-bakery/cards", json={"amount": "100"})
    assert over.status_code == 409 and "$50.00" in over.json()["detail"]
    page = client.get("/reopen/morenos-bakery").json()
    assert page["campaign"]["cards_sold"] == 3 and page["supporters"] == ["Ana", "Ana", "Ana"]


def test_tranches_need_money_in_escrow_and_staff_approval(luis, paypal):
    biz = live_campaign(luis)
    ovens = biz["campaign"]["tranches"][0]
    too_early = client.post(
        f"/business/me/tranches/{ovens['id']}/request", headers=luis, json={"note": "Invoice attached"}
    )
    assert too_early.status_code == 409 and "escrow" in too_early.json()["detail"]
    for _ in range(4):
        buy("200")
    assert (
        client.post(f"/business/me/tranches/{ovens['id']}/request", headers=luis, json={"note": "Invoice"}).status_code
        == 200
    )
    assert (
        client.post(f"/command/tranches/{ovens['id']}/decide", headers=luis, json={"approve": True}).status_code == 403
    )
    released = client.post(
        f"/command/tranches/{ovens['id']}/decide",
        headers=login_as("Grace Alvarez"),
        json={"approve": True, "note": "Matches the invoice"},
    ).json()
    assert released["status"] == "released"
    assert paypal["payouts"] == [("luis.moreno@business.example.com", D("700.00"))]
    assert client.get("/business/me", headers=luis).json()["campaign"]["escrow"] == "100.00"


def test_cards_are_spent_only_after_reopening(luis, paypal):
    live_campaign(luis)
    card = buy("100")
    early = client.post("/business/me/redeem", headers=luis, json={"code": card["code"], "amount": "10"})
    assert early.status_code == 409 and "reopened" in early.json()["detail"]
    assert client.post("/business/me/reopened", headers=luis).json()["campaign"]["status"] == "reopened"
    spent = client.post("/business/me/redeem", headers=luis, json={"code": card["code"], "amount": "45.50"}).json()
    assert spent["balance"] == "74.50"  # $100 + 20% bonus - $45.50
    assert (
        client.post("/business/me/redeem", headers=luis, json={"code": card["code"], "amount": "80"}).status_code == 409
    )
    assert (
        client.post("/reopen/morenos-bakery/cards", json={"amount": "20"}).status_code == 409
    )  # sales end at reopening


def test_missing_the_deadline_refunds_what_is_left_in_proportion(luis, paypal):
    biz = live_campaign(luis)
    for amount in ("300", "200", "100", "400"):
        buy(amount)
    ovens = biz["campaign"]["tranches"][0]
    client.post(f"/business/me/tranches/{ovens['id']}/request", headers=luis, json={})
    client.post(f"/command/tranches/{ovens['id']}/decide", headers=login_as("Sam Whitfield"), json={"approve": True})
    with SessionLocal() as db:
        c = db.query(ReopenCampaign).one()
        c.reopen_by = datetime.now(UTC) - timedelta(days=1)
        db.commit()
    assert client.post("/command/reopen/deadlines", headers=login_as("Sam Whitfield")).json() == {
        "refunded_campaigns": [c.id]
    }
    # $1,000 raised, $700 paid out for the ovens: the $300 left goes back 30% to each buyer.
    assert sorted(a for _, a in paypal["refunds"]) == [D("30.00"), D("60.00"), D("90.00"), D("120.00")]
    with SessionLocal() as db:
        assert reopen.escrow_balance(db, c.id) == D("0.00")
        assert {g.status for g in db.query(GiftCard)} == {"refunded"}
        assert db.get(ReopenCampaign, c.id).status == "refunded"


def test_shares_add_up_to_the_cent():
    assert reopen._shares(D("100.00"), [D("1"), D("1"), D("1")]) == [D("33.34"), D("33.33"), D("33.33")]
    assert sum(reopen._shares(D("299.99"), [D("50"), D("25"), D("75"), D("25")])) == D("299.99")


def test_reopening_plan_gantt(luis, paypal):
    biz = live_campaign(luis)
    data = client.get("/bryntum/reopen/morenos-bakery/load").json()
    children = data["tasks"]["rows"][0]["children"]
    assert [c["status"] for c in children] == ["pending", "pending", "milestone"]
    step = biz["campaign"]["tranches"][1]
    move = {"tasks": {"updated": [{"id": step["id"], "startDate": (SOON - timedelta(days=5)).isoformat()}]}}
    assert (
        client.post("/bryntum/reopen/morenos-bakery/sync", headers=login_as("Marcus Chen"), json=move).status_code
        == 403
    )
    assert client.post("/bryntum/reopen/morenos-bakery/sync", headers=luis, json=move).json()["success"] is True


@pytest.fixture
def subs(monkeypatch):
    """Fake PayPal Subscriptions: plans, subscriptions, status, payments, cancellations and sale refunds."""
    from app.paypal import subscriptions

    calls = {"plans": [], "subs": [], "cancelled": [], "refunds": [], "status": "APPROVAL_PENDING", "payments": []}

    def create_plan(*, name, description, amount, months, request_id):
        calls["plans"].append((name, amount, months))
        return f"P-{len(calls['plans'])}"

    def subscribe(*, plan_id, custom_id, brand, return_url, cancel_url):
        calls["subs"].append((plan_id, custom_id, return_url))
        n = len(calls["subs"])
        return subscriptions.NewSubscription(
            id=f"I-SUB{n}", approval_url=f"https://www.sandbox.paypal.com/approve/{n}", status="APPROVAL_PENDING"
        )

    monkeypatch.setattr(subscriptions, "create_plan", create_plan)
    monkeypatch.setattr(subscriptions, "subscribe", subscribe)
    monkeypatch.setattr(subscriptions, "status", lambda sid: calls["status"])
    monkeypatch.setattr(subscriptions, "payments", lambda sid: calls["payments"])
    monkeypatch.setattr(subscriptions, "cancel", lambda sid, reason: calls["cancelled"].append(sid))
    monkeypatch.setattr(
        subscriptions, "refund_sale", lambda sale, amount: calls["refunds"].append((sale, amount)) or "completed"
    )
    return calls


def sale(event_id: str, sale_id: str, sub_id: str, amount: str = "20.00") -> dict:
    return {
        "id": event_id,
        "event_type": "PAYMENT.SALE.COMPLETED",
        "resource": {
            "id": sale_id,
            "billing_agreement_id": sub_id,
            "amount": {"total": amount},
            "transaction_fee": {"value": "1.19"},
        },
    }


def test_regulars_prepay_monthly_and_each_payment_tops_up_their_card(luis, paypal, subs):
    live_campaign(luis)
    first = client.post("/reopen/morenos-bakery/regulars", json={"buyer_name": "Ana"}).json()
    second = client.post("/reopen/morenos-bakery/regulars", json={"buyer_name": "Bo"}).json()
    assert first["approval_url"].startswith("https://www.sandbox.paypal.com/") and len(subs["plans"]) == 1  # one plan
    assert subs["plans"][0] == ("Moreno's Bakery regulars", D("20.00"), 6)
    assert subs["subs"][0][2].endswith(f"/paid?kind=regular&id={first['regular_id']}&t={first['token']}")
    assert client.post(f"/regulars/{first['regular_id']}/sync").status_code == 404  # a guessed id shows nothing
    with SessionLocal() as db:
        for event in (
            sale("WH-S1", "SALE-1", "I-SUB1"),
            sale("WH-S2", "SALE-2", "I-SUB1"),
            sale("WH-S1b", "SALE-1", "I-SUB1"),
        ):
            handle(db, event, verified=True)  # the third repeats the first sale: counted once
    card = client.post(f"/regulars/{first['regular_id']}/sync", params={"token": first["token"]}).json()
    assert card["status"] == "active" and card["payments"] == 2
    assert card["card"]["face_value"] == "48.00" and card["card"]["balance"] == "48.00"  # 2 x $20 + 20% bonus
    page = client.get("/reopen/morenos-bakery").json()["campaign"]
    assert page["raised"] == "40.00" and page["regulars"] == 1 and page["regular_monthly"] == "20.00"
    subs["status"], subs["payments"] = "ACTIVE", [("SALE-9", D("20.00"), D("1.19"))]
    synced = client.post(f"/regulars/{second['regular_id']}/sync", params={"token": second["token"]}).json()
    assert synced["status"] == "active" and synced["card"]["balance"] == "24.00"


def test_missing_the_deadline_cancels_regulars_and_refunds_their_payments(luis, paypal, subs):
    live_campaign(luis)
    regular = client.post("/reopen/morenos-bakery/regulars", json={"buyer_name": "Ana"}).json()
    with SessionLocal() as db:
        handle(db, sale("WH-1", "SALE-1", "I-SUB1"), verified=True)
        handle(db, sale("WH-2", "SALE-2", "I-SUB1"), verified=True)
    buy("60")  # an ordinary card too
    with SessionLocal() as db:
        c = db.query(ReopenCampaign).one()
        c.reopen_by = datetime.now(UTC) - timedelta(days=1)
        db.commit()
    client.post("/command/reopen/deadlines", headers=login_as("Sam Whitfield"))
    assert subs["cancelled"] == ["I-SUB1"]
    assert subs["refunds"] == [
        ("SALE-2", D("20.00")),
        ("SALE-1", D("20.00")),
    ]  # newest first, all of it (nothing released)
    card = client.post(f"/regulars/{regular['regular_id']}/sync", params={"token": regular["token"]}).json()
    assert card["card"]["status"] == "refunded" and card["card"]["refunded_amount"] == "40.00"


def test_the_public_page_keeps_staffs_notes_private(luis, paypal):
    live_campaign(luis)
    page = client.get("/reopen/morenos-bakery").json()
    assert page["verification_note"] is None
    assert all(t["request_note"] is None and t["decision_note"] is None for t in page["campaign"]["tranches"])
