from decimal import Decimal as D

import pytest
from fastapi.testclient import TestClient

from app import reopen, seed_prices, seed_reopen
from app.db import SessionLocal
from app.main import app
from app.paypal import orders
from app.paypal.orders import Capture
from tests.helpers import client, login_as


@pytest.fixture
def paypal(monkeypatch):
    made = []

    def create(*, amount, description, custom_id, reference_id, return_url=None, cancel_url=None):
        made.append({"custom_id": custom_id, "amount": amount, "return_url": return_url, "cancel_url": cancel_url})
        n = len(made)
        return f"ORDER-{n}", f"https://www.sandbox.paypal.com/checkoutnow?token=ORDER-{n}"

    monkeypatch.setattr(orders, "create_order_with_link", create)
    monkeypatch.setattr(
        orders,
        "capture_order",
        lambda oid: Capture(
            oid, f"CAP-{oid}", "COMPLETED", made[int(oid.split("-")[1]) - 1]["amount"], D("1.00"), "paypal"
        ),
    )
    login_as("Elena Rivera")  # seeds the demo town
    return made


def test_find_and_read_registries(paypal):
    found = client.get("/v1/registries", params={"q": "mattress"}).json()
    assert [r["slug"] for r in found] == ["rivera-family"] and D(found[0]["still_needed"]) > 0
    assert client.get("/v1/registries", params={"q": "grand piano"}).json() == []
    phrase = client.get("/v1/registries", params={"q": "winter coats and the jackets for kids"}).json()
    assert [r["slug"] for r in phrase] == ["rivera-family"]  # any of the words, not the whole phrase
    detail = client.get("/v1/registries/rivera-family").json()
    assert detail["url"].endswith("/r/rivera-family") and "214 Juniper" not in str(detail)  # no house number
    assert {i["name"] for i in detail["items"]} >= {"Twin mattresses", "Steel-toe work boots"}
    assert client.get("/v1/registries/nope").status_code == 404


def test_an_agent_prepares_a_gift_and_a_person_approves_it(paypal):
    item = next(i for i in client.get("/v1/registries/rivera-family").json()["items"] if i["name"] == "Twin mattresses")
    checkout = client.post(
        "/v1/registries/rivera-family/donations",
        json={"amount": "40", "item_id": item["id"], "donor_name": "An agent's user"},
    )
    assert checkout.status_code == 201, checkout.text
    c = checkout.json()
    assert c["approval_url"].startswith("https://www.sandbox.paypal.com/") and "approve" in c["note"]
    assert paypal[0]["return_url"].endswith(f"/paid?kind=donation&id={c['id']}")  # PayPal brings them back here
    assert client.get(f"/v1/donations/{c['id']}").json()["status"] == "created"  # not paid until approved
    client.post(f"/donations/{c['id']}/capture")  # what the return page does after approval
    status = client.get(f"/v1/donations/{c['id']}").json()
    assert status["status"] == "captured" and status["item"] == "Twin mattresses"
    assert [e["event"] for e in status["timeline"]][:2] == ["Gift prepared", "Paid $40.00 with paypal"]
    too_much = client.post("/v1/registries/rivera-family/donations", json={"amount": "5000", "item_id": item["id"]})
    assert too_much.status_code == 422


def test_reopen_funds_and_gift_cards(paypal):
    with SessionLocal() as db:
        seed_reopen.seed_reopen_demo(db)
        reopen.run_deadlines(db)
    funds = client.get("/v1/reopen-funds").json()
    assert [f["slug"] for f in funds] == ["morenos-bakery"]  # the refunded outfitter is left out
    assert {f["slug"] for f in client.get("/v1/reopen-funds", params={"include_closed": True}).json()} >= {
        "ridge-outfitters"
    }
    c = client.post("/v1/reopen-funds/morenos-bakery/gift-cards", json={"amount": "50", "buyer_name": "Kim"}).json()
    assert c["approval_url"] and "/v1/gift-cards/" in c["status_url"]
    card = client.post(f"/gift-cards/{c['id']}/capture").json()
    status = client.get(f"/v1/gift-cards/{card['code']}").json()
    assert status["face_value"] == "60.00" and status["usable_now"] is False  # the bakery hasn't reopened yet


def test_price_watch_filter(paypal):
    with SessionLocal() as db:
        seed_prices.seed_price_watch(db)
    gouging = client.get("/v1/price-watch", params={"status": "gouging"}).json()
    assert gouging and all(r["status"] == "gouging" for r in gouging)
    assert gouging[0]["markup_percent"] >= gouging[-1]["markup_percent"]  # worst first


def test_mcp_server_lists_and_calls_tools(paypal):
    headers = {"Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-06-18"}

    def rpc(c, method, params=None, rid=1):
        r = c.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        )
        assert r.status_code == 200, r.text
        return r.json()["result"]

    with TestClient(app) as c:  # the MCP session manager starts with the app's lifespan
        init = rpc(
            c,
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
        )
        assert "PayPal approval link" in init["instructions"]
        tools = {t["name"] for t in rpc(c, "tools/list")["tools"]}
        assert tools == {
            "find_registries",
            "get_registry",
            "prepare_donation",
            "donation_status",
            "find_reopen_funds",
            "prepare_gift_card",
            "price_watch",
        }
        found = rpc(c, "tools/call", {"name": "find_registries", "arguments": {"query": "laptop"}})
        assert found["structuredContent"]["result"][0]["slug"] == "rivera-family"
        prepared = rpc(
            c, "tools/call", {"name": "prepare_donation", "arguments": {"slug": "rivera-family", "amount": 25}}
        )
        assert prepared["structuredContent"]["approval_url"].startswith("https://www.sandbox.paypal.com/")


def test_a_registry_under_fraud_review_is_not_recommended(paypal):
    from app import review
    from app.models import Household, Registry

    with SessionLocal() as db:
        home = db.query(Household).filter_by(name="Rivera household").one()
        case = review.open_case(db, home, kind="registry_verification", title="Check", explain=False)
        case.risk_tier = "high"
        db.commit()
        slug = db.query(Registry).filter_by(household_id=home.id).one().slug
    assert slug not in {r["slug"] for r in client.get("/v1/registries").json()}
    assert client.get(f"/v1/registries/{slug}").status_code == 200  # a direct link still works
