"""Giving mandates, through APIMatic's PayPal SDK with its network replaced by the routing stub (the real client and
request pipeline still run). Contract: paypal-plan.md, Part 2."""

from decimal import Decimal as D

import httpx2
import pytest

from app import ai, mandates
from app.agents import giving
from app.db import SessionLocal
from app.models import Donation, GivingMandate, Household, MandateGift, RegistryItem
from tests.helpers import client, login_as
from tests.paypal_stub import StubResponse, json_response

SETUP = "/v3/vault/setup-tokens"
TOKENS = "/v3/vault/payment-tokens"
ORDERS = "/v2/checkout/orders"
BOOTS, CRATE = "Steel-toe work boots", "Dog crate and bed for Pepper"


@pytest.fixture
def vault(paypal_reporting, monkeypatch):
    """PayPal's vault and orders, stubbed. Orders complete with one capture per PayPal-Request-Id, like the sandbox."""
    transport = paypal_reporting
    orders: dict[str, dict] = {}
    transport.routes[SETUP] = json_response(
        201,
        {
            "id": "SETUP-1",
            "status": "PAYER_ACTION_REQUIRED",
            "customer": {"id": "CUST-1"},
            "links": [
                {
                    "href": "https://www.sandbox.paypal.com/agreements/approve?approval_session_id=SETUP-1",
                    "rel": "approve",
                    "method": "GET",
                }
            ],
        },
    )
    transport.routes[f"{SETUP}/SETUP-1"] = json_response(200, {"id": "SETUP-1", "status": "APPROVED"})
    transport.routes[TOKENS] = json_response(
        200,
        {
            "id": "VAULT-1",
            "customer": {"id": "CUST-1"},
            "payment_source": {"paypal": {"email_address": "marcus@personal.example.com", "payer_id": "PAYER-1"}},
        },
    )
    transport.routes[f"{TOKENS}/VAULT-1"] = lambda request: (
        StubResponse(204) if request.method == "DELETE" else json_response(200, {"id": "VAULT-1"})
    )

    def create_order(request):
        headers = {k.lower(): v for k, v in request.headers.items()}
        request_id = headers.get("paypal-request-id")
        if not request_id:
            return json_response(
                400, {"name": "INVALID_REQUEST", "message": "PAYPAL_REQUEST_ID_REQUIRED", "debug_id": "stub"}
            )
        body = request.body.value
        unit = body["purchase_units"][0]
        n = orders.setdefault(request_id, {"n": len(orders) + 1})["n"]
        return json_response(
            201,
            {
                "id": f"ORDER-{n}",
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "custom_id": unit["custom_id"],
                        "payments": {
                            "captures": [
                                {
                                    "id": f"CAPTURE-{n}",
                                    "status": "COMPLETED",
                                    "amount": unit["amount"],
                                    "final_capture": True,
                                    "seller_receivable_breakdown": {
                                        "gross_amount": unit["amount"],
                                        "paypal_fee": {"currency_code": "USD", "value": "0.99"},
                                    },
                                }
                            ]
                        },
                    }
                ],
            },
        )

    transport.routes[ORDERS] = create_order
    monkeypatch.setattr(giving, "choose", _no_ai)  # tests choose with the fallback unless they set a plan
    return transport


def _no_ai(*args, **kwargs):
    raise ai.AIError("no AI in tests")


def order_requests(transport):
    return [r for r in transport.requests if r.url.endswith(ORDERS)]


def item_id(name: str) -> int:
    with SessionLocal() as db:
        return db.query(RegistryItem).filter_by(name=name).one().id


def verify_riveras(level: int = 3) -> None:
    """The demo verifies the Riveras with their pre-disaster inventory (level 3); the test seed leaves that out."""
    with SessionLocal() as db:
        db.query(Household).filter_by(name="Rivera household").one().verification_level = level
        db.commit()


def start(donor, **limits) -> dict:
    body = {"states": ["CA"], "per_gift_max": "50", "monthly_max": "120", "note": "kids and pets"} | limits
    r = client.post("/donors/me/mandates", json=body, headers=donor)
    assert r.status_code == 201, r.text
    return r.json()


def active(donor, **limits) -> dict:
    verify_riveras()
    started = start(donor, **limits)
    assert "approval_session_id=SETUP-1" in started["approve_url"]
    r = client.post("/donors/me/mandates/finish", json={"setup_id": "SETUP-1"}, headers=donor)
    assert r.status_code == 200, r.text
    return r.json()


def test_a_donor_saves_their_paypal_account_and_the_agent_gives_within_limits(vault, monkeypatch):
    marcus = login_as("Marcus Chen")
    mandate = active(marcus)
    assert (mandate["status"], mandate["paypal_email"]) == ("active", "marcus@personal.example.com")

    boots, crate = item_id(BOOTS), item_id(CRATE)

    def plan(instruction, needs, budget, per_gift):
        assert instruction == "kids and pets" and budget == D("120") and per_gift == D("50")
        assert {boots, crate} <= {n.item_id for n in needs}
        wanted = [(crate, D("95"), "Pepper's crate"), (boots, D("50"), "Work boots"), (crate, D("5"), "again")]
        return giving.check(needs, wanted, budget, per_gift), "Two gifts for the Riveras"

    monkeypatch.setattr(giving, "choose", plan)
    r = client.post(f"/donors/me/mandates/{mandate['id']}/run", headers=marcus).json()
    assert (r["given"], r["summary"], r["by_ai"]) == (2, "Two gifts for the Riveras", True)
    gifts = {g["item"]: g for g in r["mandate"]["gifts"]}
    assert gifts[CRATE]["amount"] == "50.00" and gifts[BOOTS]["amount"] == "50.00"  # each capped at $50 a gift
    assert r["mandate"]["given_this_month"] == "100.00" and r["mandate"]["left_this_month"] == "20.00"

    sent = order_requests(vault)
    headers = {k.lower(): v for k, v in sent[0].headers.items()}
    assert headers["paypal-request-id"] == f"hearthline-mandate-{mandate['id']}-item-{crate}"
    source = sent[0].body.value["payment_source"]["paypal"]
    assert source["vault_id"] == "VAULT-1"
    assert source["stored_credential"] == {
        "payment_initiator": "MERCHANT",
        "usage": "SUBSEQUENT",
        "usage_pattern": "UNSCHEDULED_PREPAID",
    }
    with SessionLocal() as db:
        donation = db.query(Donation).filter_by(paypal_order_id="ORDER-1").one()
        assert sent[0].body.value["purchase_units"][0]["custom_id"] == f"donation:{donation.id}"
        assert (donation.status, donation.donor_user_id is not None, donation.fee) == ("captured", True, D("0.99"))
        assert db.get(RegistryItem, crate).funded_amount == D("50.00")  # an ordinary gift from here on


def test_the_monthly_limit_holds_across_rounds(vault):
    marcus = login_as("Marcus Chen")
    mandate = active(marcus, per_gift_max="40", monthly_max="80")
    first = client.post(f"/donors/me/mandates/{mandate['id']}/run", headers=marcus).json()
    assert first["given"] == 2 and first["mandate"]["given_this_month"] == "80.00"
    second = client.post(f"/donors/me/mandates/{mandate['id']}/run", headers=marcus).json()
    assert (second["given"], second["summary"]) == (0, "You've reached this month's limit.")
    assert len(order_requests(vault)) == 2


def test_the_agent_is_held_to_the_listed_needs_and_the_limits():
    needs = [
        giving.Need(1, "Boots", "", "clothing", D("139"), "Rivera household", "Sablewood, CA", "Sablewood Fire"),
        giving.Need(2, "Crate", "", "other", D("12.50"), "Rivera household", "Sablewood, CA", "Sablewood Fire"),
    ]
    plan = giving.check(
        needs,
        [(99, D("10"), "not listed"), (1, D("500"), "boots"), (1, D("5"), "boots again"), (2, D("40"), "crate")],
        budget=D("60"),
        per_gift=D("50"),
    )
    assert [(p.item_id, p.amount) for p in plan] == [(1, D("50")), (2, D("10"))]  # capped, deduped, within budget


def test_a_need_is_given_once_per_mandate_and_saving_twice_saves_once(vault):
    marcus = login_as("Marcus Chen")
    mandate = active(marcus)
    again = client.post("/donors/me/mandates/finish", json={"setup_id": "SETUP-1"}, headers=marcus)
    assert again.status_code == 200 and again.json()["status"] == "active"
    assert len([r for r in vault.requests if r.url.endswith(TOKENS)]) == 1  # one saved account, not two

    with SessionLocal() as db:
        m = db.get(GivingMandate, mandate["id"])
        planned = giving.PlannedGift(item_id(CRATE), D("10"), "crate")
        assert mandates._give(db, m, planned, by_ai=False).status == "given"
        assert mandates._give(db, m, planned, by_ai=False) is None  # the claim refuses a second gift
    assert len(order_requests(vault)) == 1


def test_an_unknown_outcome_is_settled_by_resending_the_same_request(vault):
    marcus = login_as("Marcus Chen")
    mandate = active(marcus, per_gift_max="10", monthly_max="10", categories=["other"])
    answer = vault.routes[ORDERS]

    def times_out(request):
        raise httpx2.ReadTimeout("no reply", request=None)

    vault.routes[ORDERS] = times_out
    client.post(f"/donors/me/mandates/{mandate['id']}/run", headers=marcus)
    with SessionLocal() as db:
        gift = db.query(MandateGift).one()
        assert gift.status == "checking" and gift.donation.status == "created"  # it may have landed

    vault.routes[ORDERS] = answer
    client.post(f"/donors/me/mandates/{mandate['id']}/run", headers=marcus)
    with SessionLocal() as db:
        gift = db.query(MandateGift).one()
        assert (gift.status, gift.donation.status) == ("given", "captured")
    ids = [{k.lower(): v for k, v in r.headers.items()}["paypal-request-id"] for r in order_requests(vault)]
    assert ids == [gift.paypal_request_id] * 2  # the resend used the timed-out attempt's id: PayPal dedups on it


def test_a_declined_payment_fails_the_gift_and_funds_nothing(vault):
    marcus = login_as("Marcus Chen")
    mandate = active(marcus, per_gift_max="10", monthly_max="10", categories=["other"])
    vault.routes[ORDERS] = json_response(
        422,
        {
            "name": "UNPROCESSABLE_ENTITY",
            "message": "declined",
            "debug_id": "stub",
            "details": [{"issue": "INSTRUMENT_DECLINED"}],
        },
    )
    r = client.post(f"/donors/me/mandates/{mandate['id']}/run", headers=marcus).json()
    gift = r["mandate"]["gifts"][0]
    assert r["given"] == 0 and gift["status"] == "failed" and "INSTRUMENT_DECLINED" in gift["error"]
    assert r["mandate"]["given_this_month"] == "0.00"
    with SessionLocal() as db:
        assert db.get(RegistryItem, item_id(CRATE)).funded_amount == D("0")


def test_revoking_deletes_the_saved_account_and_stops_giving(vault):
    marcus = login_as("Marcus Chen")
    mandate = active(marcus)
    paused = client.post(f"/donors/me/mandates/{mandate['id']}/pause", headers=marcus).json()
    assert paused["status"] == "paused"
    assert client.post(f"/donors/me/mandates/{mandate['id']}/run", headers=marcus).status_code == 409
    revoked = client.post(f"/donors/me/mandates/{mandate['id']}/revoke", headers=marcus).json()
    assert revoked["status"] == "revoked" and revoked["error"] is None
    deletes = [r for r in vault.requests if r.method == "DELETE"]
    assert len(deletes) == 1 and deletes[0].url.endswith(f"{TOKENS}/VAULT-1")
    assert client.post(f"/donors/me/mandates/{mandate['id']}/resume", headers=marcus).status_code == 409


def test_only_verified_families_in_active_disasters_in_the_chosen_places(vault):
    marcus = login_as("Marcus Chen")
    with SessionLocal() as db:
        m = db.get(GivingMandate, active(marcus)["id"])
        assert {n.family for n in mandates.eligible(db, m)} == {"Rivera household"}
    verify_riveras(level=1)  # address inside the fire, residence not confirmed
    with SessionLocal() as db:
        m = db.get(GivingMandate, m.id)
        assert mandates.eligible(db, m) == []
    verify_riveras(level=2)
    with SessionLocal() as db:
        m = db.get(GivingMandate, m.id)
        assert mandates.eligible(db, m) != []
        m.states = ["NV"]
        assert mandates.eligible(db, m) == []
        m.states, m.categories = [], ["electronics"]
        assert {n.item for n in mandates.eligible(db, m)} == {"School laptop for Maya"}


def test_limits_and_ownership_are_checked(vault):
    marcus = login_as("Marcus Chen")
    too_big = client.post("/donors/me/mandates", json={"per_gift_max": "900", "monthly_max": "900"}, headers=marcus)
    assert too_big.status_code == 422
    wrong_state = client.post(
        "/donors/me/mandates", json={"states": ["ZZ"], "per_gift_max": "10", "monthly_max": "20"}, headers=marcus
    )
    assert wrong_state.status_code == 422
    mandate_id = start(marcus)["mandate"]["id"]
    elena = login_as("Elena Rivera")
    assert client.get("/donors/me/mandates", headers=elena).status_code == 403  # donors only
    marcus = login_as("Marcus Chen")
    assert client.post(f"/donors/me/mandates/{mandate_id + 1}/pause", headers=marcus).status_code == 404
    assert client.post(f"/donors/me/mandates/{mandate_id}/pause", headers=marcus).status_code == 409  # not saved yet
