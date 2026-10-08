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
    return client.post(f"/gift-cards/{started.json()['card_id']}/capture").json()


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
