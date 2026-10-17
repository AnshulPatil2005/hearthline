import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app import ai, disputes, ledger, registry, reopen
from app.db import SessionLocal
from app.models import (
    Business,
    Case,
    Donation,
    GiftCard,
    LedgerTransaction,
    PaymentDispute,
    Purchase,
    RegistryItem,
    ReopenCampaign,
    User,
)
from app.paypal import disputes as paypal_disputes
from app.paypal.orders import Capture
from app.paypal.webhooks import handle
from tests.helpers import client, login_as

_events = itertools.count(1)
ALL_ACTIONS = ("send_message", "provide_evidence", "accept_claim")


@pytest.fixture
def pp(monkeypatch):
    """Fake PayPal Disputes API: responses are recorded, never sent. AI is off unless a test turns it on."""
    calls = []
    monkeypatch.setattr(paypal_disputes, "send_message", lambda i, m: calls.append(("message", i, m)))
    monkeypatch.setattr(
        paypal_disputes,
        "provide_evidence",
        lambda i, kind, notes, *, tracking=None, refund_ids=None, document=None: calls.append(
            ("evidence", i, kind, tracking, document)
        ),
    )
    monkeypatch.setattr(paypal_disputes, "accept_claim", lambda i, note, amount: calls.append(("refund", i, amount)))
    monkeypatch.setattr(ai, "configured", lambda: False)
    return calls


def resource(
    dispute_id: str,
    *,
    amount: str,
    custom: str | None = None,
    txn: str | None = None,
    reason: str = "MERCHANDISE_OR_SERVICE_NOT_RECEIVED",
    status: str = "WAITING_FOR_SELLER_RESPONSE",
    stage: str = "INQUIRY",
    outcome: str | None = None,
    actions=ALL_ACTIONS,
) -> dict:
    return {
        "dispute_id": dispute_id,
        "reason": reason,
        "status": status,
        "dispute_life_cycle_stage": stage,
        "dispute_amount": {"currency_code": "USD", "value": amount},
        "disputed_transactions": [{"seller_transaction_id": txn, "custom": custom}],
        "seller_response_due_date": (datetime.now(UTC) + timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "messages": [
            {"posted_by": "BUYER", "content": "Where did my money go?"},
            {"posted_by": "SELLER", "content": "Looking into it."},
        ],
        **({"dispute_outcome": {"outcome_code": outcome}} if outcome else {}),
        "links": [{"rel": a, "href": f"https://example/{a}", "method": "POST"} for a in actions],
    }


def deliver(event_type: str, res: dict) -> None:
    with SessionLocal() as db:
        stored = handle(db, {"id": f"WH-{next(_events)}", "event_type": event_type, "resource": res}, verified=True)
        assert stored.error is None, stored.error


def dispute(paypal_id: str) -> PaymentDispute:
    with SessionLocal() as db:
        return db.query(PaymentDispute).filter_by(paypal_dispute_id=paypal_id).one()


def give(item_name: str, amount: D | None = None) -> tuple[int, int]:
    """A captured gift to the Riveras' registry item; returns (donation id, household id)."""
    login_as("Elena Rivera")
    with SessionLocal() as db:
        item = db.query(RegistryItem).filter_by(name=item_name).one()
        amount = amount or item.target_amount
        gift = Donation(
            registry_id=item.registry_id, registry_item_id=item.id, amount=amount, paypal_order_id=f"O-{item.id}"
        )
        db.add(gift)
        db.commit()
        registry.apply_capture(db, gift, Capture(f"O-{item.id}", f"CAP-{item.id}", "COMPLETED", amount, D(0), "paypal"))
        return gift.id, item.rebuild_registry.household_id


def bought(item_name: str, spent: D) -> None:
    """The Shopper bought and delivered the item with the gift (as it would, minus live calls)."""
    with SessionLocal() as db:
        item = db.query(RegistryItem).filter_by(name=item_name).one()
        home = item.rebuild_registry.household_id
        db.add(
            Purchase(
                household_id=home,
                registry_item_id=item.id,
                title="Mens Steel Toe Work Boot",
                retailer="homedepot.com",
                unit_price=spent,
                total=spent,
                status="delivered",
                carrier="UPS",
                tracking_number="1Z999AA10123456784",
                paid_at=datetime.now(UTC),
            )
        )
        ledger.record_spend(
            db, kind="purchase", household_id=home, amount=spent, paypal_ref="P-1", description="Boots", meta={}
        )
        item.status = "delivered"
        db.commit()


def test_parse_reads_the_payer_message_and_what_paypal_allows():
    info = paypal_disputes.parse(
        resource("PP-D-1", amount="12.50", custom="donation:4", txn="CAP-4", actions=("accept_claim",))
    )
    assert (info.amount, info.custom_id, info.transaction_id) == (D("12.50"), "donation:4", "CAP-4")
    assert info.payer_message == "Where did my money go?" and info.actions == ["accept_claim"]
    assert info.respond_by is not None and info.respond_by.tzinfo is None


def test_shipped_gift_gets_proof_of_fulfillment_with_the_tracking_number(pp):
    gift_id, _ = give("Steel-toe work boots")
    bought("Steel-toe work boots", D("129.99"))
    deliver("CUSTOMER.DISPUTE.CREATED", resource("PP-D-10", amount="139.00", custom=f"donation:{gift_id}"))
    d = dispute("PP-D-10")
    assert d.donation_id == gift_id and d.payer_message == "Where did my money go?"

    sam = login_as("Sam Whitfield")
    detail = client.get(f"/command/disputes/{d.id}", headers=sam).json()
    assert detail["recommended"] == "evidence" and detail["evidence_type"] == "PROOF_OF_FULFILLMENT"
    assert detail["tracking"] == [{"carrier_name": "UPS", "tracking_number": "1Z999AA10123456784"}]
    assert "delivered" in detail["because"]

    note = "The boots were bought with this gift and UPS shows them delivered to the family."
    r = client.post(f"/command/disputes/{d.id}/respond", json={"action": "evidence", "note": note}, headers=sam)
    assert r.status_code == 200 and r.json()["status"] == "UNDER_REVIEW"
    (kind, paypal_id, evidence, tracking, document), *_ = pp
    assert (kind, paypal_id, evidence) == ("evidence", "PP-D-10", "PROOF_OF_FULFILLMENT")
    assert tracking[0]["tracking_number"] == "1Z999AA10123456784"
    assert document[0] == "hearthline-PP-D-10.pdf" and document[1].startswith(b"%PDF")

    again = client.post(f"/command/disputes/{d.id}/respond", json={"action": "refund", "note": note}, headers=sam)
    assert again.status_code == 409 and len(pp) == 1


def test_refund_comes_from_the_family_fund_and_the_spent_part_is_a_loss(pp):
    gift_id, home = give("Steel-toe work boots")  # $139.00
    bought("Steel-toe work boots", D("129.99"))  # $9.01 left for the family
    deliver(
        "CUSTOMER.DISPUTE.CREATED",
        resource("PP-D-20", amount="139.00", custom=f"donation:{gift_id}", reason="UNAUTHORISED", stage="CHARGEBACK"),
    )
    d = dispute("PP-D-20")
    sam = login_as("Sam Whitfield")
    assert client.get(f"/command/disputes/{d.id}", headers=sam).json()["recommended"] == "refund"

    note = "The payer says they did not make this gift, so Hearthline is refunding it in full."
    r = client.post(f"/command/disputes/{d.id}/respond", json={"action": "refund", "note": note}, headers=sam)
    assert r.json()["decision"] == "refunded" and pp == [("refund", "PP-D-20", D("139.00"))]
    with SessionLocal() as db:
        assert db.get(Donation, gift_id).status == "refunded"
        assert ledger.household_available(db, home) == 0
        assert ledger.balance(db, ledger.DISPUTE_LOSSES) == D("129.99")

    # PayPal then closes it; the refund is not booked twice.
    deliver(
        "CUSTOMER.DISPUTE.RESOLVED",
        resource("PP-D-20", amount="139.00", status="RESOLVED", stage="CHARGEBACK", outcome="ACCEPTED", actions=()),
    )
    with SessionLocal() as db:
        assert db.query(LedgerTransaction).filter_by(paypal_ref="dispute-PP-D-20").count() == 1
        assert ledger.balance(db, ledger.DISPUTE_LOSSES) == D("129.99")


def test_a_dispute_paypal_decides_for_the_payer_is_booked_once(pp):
    gift_id, home = give("Twin mattresses", D("50.00"))
    deliver("CUSTOMER.DISPUTE.CREATED", resource("PP-D-30", amount="50.00", custom=f"donation:{gift_id}"))
    lost = resource("PP-D-30", amount="50.00", status="RESOLVED", outcome="RESOLVED_BUYER_FAVOUR", actions=())
    deliver("CUSTOMER.DISPUTE.RESOLVED", lost)
    deliver("CUSTOMER.DISPUTE.RESOLVED", lost)  # a second delivery with a new event id
    with SessionLocal() as db:
        assert db.query(LedgerTransaction).filter_by(paypal_ref="dispute-PP-D-30").count() == 1
        assert ledger.household_available(db, home) == 0
        assert db.get(Donation, gift_id).status == "refunded"
        assert db.get(RegistryItem, db.get(Donation, gift_id).registry_item_id).funded_amount == 0
    assert pp == []  # nothing was sent: PayPal decided


def test_gift_to_a_suspected_scam_is_refunded(pp):
    gift_id, home = give("Twin mattresses", D("40.00"))
    with SessionLocal() as db:
        db.add(
            Case(
                household_id=home,
                kind="registry",
                title="Registry: copycat",
                amount_requested=D(0),
                status="in_review",
                risk_tier="high",
                risk_score=90,
            )
        )
        db.commit()
    deliver(
        "CUSTOMER.DISPUTE.CREATED",
        resource(
            "PP-D-40", amount="40.00", custom=f"donation:{gift_id}", reason="MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED"
        ),
    )
    detail = client.get(f"/command/disputes/{dispute('PP-D-40').id}", headers=login_as("Sam Whitfield")).json()
    assert detail["recommended"] == "refund" and "possible scam" in detail["because"]
    assert "hasn't been spent" in detail["because"]


@pytest.fixture
def card():
    """A $100 Moreno's Bakery card (worth $120) paid by capture CAP-CARD-1, the money in escrow."""
    login_as("Luis Moreno")
    with SessionLocal() as db:
        owner = db.query(User).filter_by(name="Luis Moreno").one()
        b = Business(
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
        campaign = ReopenCampaign(
            business=b, goal_amount=D(5000), bonus_percent=20, reopen_by=datetime.now(UTC) + timedelta(days=30)
        )
        c = GiftCard(
            campaign=campaign,
            code="MOR-ABCD-WXYZ",
            buyer_name="Gus",
            amount_paid=D(100),
            face_value=D(120),
            balance=D(120),
            status="active",
            paypal_capture_id="CAP-CARD-1",
        )
        db.add_all([b, campaign, c])
        db.flush()
        ledger.post(
            db,
            kind="gift_card",
            description="card",
            paypal_ref="CAP-CARD-1",
            lines={ledger.CASH: D(100), reopen.escrow_account(campaign.id): D(-100)},
        )
        db.commit()
        return c.id, campaign.id


def test_gift_card_inquiry_gets_a_message_then_can_still_be_refunded(pp, card):
    card_id, campaign_id = card
    deliver("CUSTOMER.DISPUTE.CREATED", resource("PP-D-50", amount="100.00", txn="CAP-CARD-1"))  # no custom id
    d = dispute("PP-D-50")
    assert d.gift_card_id == card_id
    sam = login_as("Sam Whitfield")
    detail = client.get(f"/command/disputes/{d.id}", headers=sam).json()
    assert detail["kind"] == "gift_card" and detail["recommended"] == "message"
    assert "the full $100.00 comes back automatically" in detail["because"]

    note = "The bakery is still closed and your $100 is held in escrow until it reopens."
    r = client.post(f"/command/disputes/{d.id}/respond", json={"action": "message", "note": note}, headers=sam)
    assert r.json()["status"] == "WAITING_FOR_BUYER_RESPONSE" and pp[0][:2] == ("message", "PP-D-50")

    r = client.post(f"/command/disputes/{d.id}/respond", json={"action": "refund", "note": note}, headers=sam)
    assert r.json()["decision"] == "refunded"
    with SessionLocal() as db:
        c = db.get(GiftCard, card_id)
        assert (c.status, c.balance, c.refunded_amount) == ("refunded", 0, D(100))
        assert reopen.escrow_balance(db, campaign_id) == 0
        assert ledger.balance(db, ledger.DISPUTE_LOSSES) == 0


def test_refunded_card_gets_proof_of_refund(pp, card):
    card_id, _ = card
    with SessionLocal() as db:
        c = db.get(GiftCard, card_id)
        c.status, c.refunded_amount, c.balance = "refunded", D("60.00"), D(0)
        db.commit()
    deliver(
        "CUSTOMER.DISPUTE.CREATED",
        resource("PP-D-60", amount="40.00", custom=f"giftcard:{card_id}", reason="CREDIT_NOT_PROCESSED"),
    )
    detail = client.get(f"/command/disputes/{dispute('PP-D-60').id}", headers=login_as("Sam Whitfield")).json()
    assert detail["evidence_type"] == "PROOF_OF_REFUND" and "$60.00" in detail["because"]


def test_paypal_decides_which_answers_are_possible(pp):
    gift_id, _ = give("Twin mattresses", D("30.00"))
    deliver(
        "CUSTOMER.DISPUTE.CREATED",
        resource("PP-D-70", amount="30.00", custom=f"donation:{gift_id}", actions=("accept_claim",)),
    )
    d = dispute("PP-D-70")
    sam = login_as("Sam Whitfield")
    assert client.get(f"/command/disputes/{d.id}", headers=sam).json()["recommended"] == "refund"
    note = "Our records show the gift is held for the family and will buy the mattresses."
    r = client.post(f"/command/disputes/{d.id}/respond", json={"action": "evidence", "note": note}, headers=sam)
    assert r.status_code == 409 and "doesn't allow" in r.json()["detail"] and pp == []


def test_draft_is_written_by_the_funds_agent_or_a_template(pp, monkeypatch):
    gift_id, _ = give("Twin mattresses", D("30.00"))
    deliver("CUSTOMER.DISPUTE.CREATED", resource("PP-D-80", amount="30.00", custom=f"donation:{gift_id}"))
    d = dispute("PP-D-80")
    sam = login_as("Sam Whitfield")
    plain = client.post(f"/command/disputes/{d.id}/draft", headers=sam).json()
    assert plain["draft"].startswith("Thank you for raising this.") and not plain["draft_by_ai"]

    seen = {}

    def parse(schema, *, system, content, max_tokens):
        seen["facts"] = content[0]["text"]
        return disputes.Draft(note="Your $30.00 gift on Oct 1 is held for the Rivera family to buy the mattresses.")

    monkeypatch.setattr(ai, "configured", lambda: True)
    monkeypatch.setattr(ai, "parse", parse)
    kept = client.post(f"/command/disputes/{d.id}/draft", headers=sam).json()
    assert kept["draft"] == plain["draft"]  # an existing draft is kept unless asked again
    by_ai = client.post(f"/command/disputes/{d.id}/draft?again=true", headers=sam).json()
    assert by_ai["draft_by_ai"] and by_ai["draft"].startswith("Your $30.00 gift")
    assert "recommended_action" in seen["facts"] and "Where did my money go?" in seen["facts"]


def test_staff_only_and_sync(pp, monkeypatch):
    gift_id, _ = give("Twin mattresses", D("30.00"))
    monkeypatch.setattr(
        paypal_disputes,
        "recent",
        lambda days=180: [paypal_disputes.parse(resource("PP-D-90", amount="30.00", custom=f"donation:{gift_id}"))],
    )
    assert client.get("/command/disputes", headers=login_as("Elena Rivera")).status_code == 403
    sam = login_as("Sam Whitfield")
    assert client.post("/command/disputes/sync", headers=sam).json() == {"seen": 1}
    assert client.post("/command/disputes/sync", headers=sam).json() == {"seen": 1}  # no duplicate
    rows = client.get("/command/disputes", headers=sam).json()
    assert [(r["paypal_dispute_id"], r["kind"], r["amount"]) for r in rows] == [("PP-D-90", "donation", "30.00")]
    pdf = client.get(f"/command/disputes/{rows[0]['id']}/evidence.pdf", headers=sam)
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
