from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import httpx2

from app import audit
from app.db import SessionLocal
from app.models import AuditEvent, Case, Donation, Household, Milestone, Registry, ReopenTranche
from app.paypal import reporting
from tests.helpers import client, login_as
from tests.paypal_stub import (
    BALANCES_PATH,
    TOKEN_PATH,
    TRANSACTIONS_PATH,
    balances_body,
    json_response,
    transaction,
    transactions_body,
)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_balance_comes_from_paypal_through_the_sdk(paypal_reporting):
    paypal_reporting.routes[BALANCES_PATH] = json_response(
        200, balances_body("9247.26", refreshed="2026-10-19T09:29:59Z")
    )
    body = client.get("/command/books/balance", headers=login_as("Sam Whitfield")).json()
    assert body["available"] == "9247.26" and body["as_of"].startswith("2026-10-19T09:29:59")
    paths = [r.url.split("?")[0].removeprefix("https://api-m.sandbox.paypal.com") for r in paypal_reporting.requests]
    assert paths == [TOKEN_PATH, BALANCES_PATH]  # the SDK fetched the token first, then the balance
    assert paypal_reporting.calls(BALANCES_PATH) == [{"currency_code": ["USD"]}]
    assert {k.lower(): v for k, v in paypal_reporting.requests[-1].headers.items()}["authorization"] == "Bearer t"


def test_each_failure_kind_becomes_a_clear_answer(paypal_reporting):
    sam = login_as("Sam Whitfield")
    refused = {"name": "NOT_AUTHORIZED", "message": "Authorization failed", "debug_id": "x"}
    paypal_reporting.routes[BALANCES_PATH] = json_response(403, refused)
    r = client.get("/command/books/balance", headers=sam)
    assert (r.status_code, r.json()["detail"]) == (502, "PayPal refused our credentials for Transaction Search")

    def refuse_token(request):
        return json_response(401, {"error": "invalid_client", "error_description": "Client Authentication failed"})

    reporting.close()  # a fresh client, so the token is fetched again
    from tests.paypal_stub import stub_client

    reporting._client = stub_client(paypal_reporting)
    paypal_reporting.routes[TOKEN_PATH] = refuse_token
    assert client.get("/command/books/balance", headers=sam).status_code == 502

    def unsent(request):
        raise httpx2.ConnectError("refused")

    def no_reply(request):
        raise httpx2.ReadTimeout("no reply")

    from tests.paypal_stub import token_response

    paypal_reporting.routes[TOKEN_PATH] = token_response()
    paypal_reporting.routes[BALANCES_PATH] = unsent
    never_sent = client.get("/command/books/balance", headers=sam)
    paypal_reporting.routes[BALANCES_PATH] = no_reply
    unknown = client.get("/command/books/balance", headers=sam)
    assert (never_sent.status_code, never_sent.json()["detail"]) == (502, "Couldn't reach PayPal")
    assert (unknown.status_code, unknown.json()["detail"]) == (504, "PayPal didn't answer in time")

    paypal_reporting.routes[BALANCES_PATH] = json_response(200, {"balances": [{"currency": "USD"}]})  # no total
    assert client.get("/command/books/balance", headers=sam).status_code == 502  # unreadable, not "zero"


def test_reconciliation_traces_every_dollar(paypal_reporting):
    sam = login_as("Sam Whitfield")
    now = datetime.now(UTC)
    with SessionLocal() as db:
        opened = now - timedelta(days=2)
        audit.record(db, action="demo.seeded", subject_type="demo", subject_id="test")
        db.query(AuditEvent).filter_by(action="demo.seeded").update({"created_at": opened})
        reg = db.query(Registry).filter_by(slug="rivera-family").one()
        home = db.get(Household, reg.household_id)
        gift = Donation(
            registry_id=reg.id,
            amount=D("25.00"),
            status="captured",
            paypal_order_id="O-REAL",
            paypal_capture_id="CAPREAL0000000001",
            captured_at=now - timedelta(hours=6),
        )
        old_gift = Donation(  # before the books opened: not this report's business
            registry_id=reg.id,
            amount=D("9.00"),
            status="captured",
            paypal_order_id="O-OLD",
            paypal_capture_id="CAPOLD00000000001",
            captured_at=now - timedelta(days=5),
        )
        demo_gift = Donation(  # seeded demo data never touched PayPal
            registry_id=reg.id,
            amount=D("40.00"),
            status="captured",
            paypal_order_id="DEMO-O-1",
            paypal_capture_id="DEMO-CAP-1",
            captured_at=now - timedelta(hours=5),
        )
        aid = Case(
            household_id=home.id,
            kind="cash_aid",
            title="Cash aid",
            amount_requested=D("300.00"),
            status="approved",
            paypal_ref="5UXD2E8A7EBQJ",  # PayPal's own payout batch id, as stored
            decided_at=now - timedelta(hours=5),
        )
        db.add_all([gift, old_gift, demo_gift, aid])
        db.commit()
        case_id = aid.id
        milestone = db.query(Milestone).first()
        tranche = db.query(ReopenTranche).first()
        if milestone is not None:  # paid in our books, absent from PayPal's report: missing
            milestone.paypal_ref, milestone.paid_at, milestone.amount = (
                "8KQW3BZ9N2TRL",
                now - timedelta(hours=8),
                D("1200.00"),
            )
        if tranche is not None:  # paid after PayPal's report was refreshed: waiting
            tranche.paypal_ref, tranche.released_at = "3HTV9C2LQ8MXA", now - timedelta(minutes=10)
        db.commit()
        milestone_id = milestone.id if milestone else None

    refreshed = iso(now - timedelta(hours=1))
    paypal_reporting.routes[TRANSACTIONS_PATH] = json_response(
        200,
        transactions_body(
            [
                transaction("CAPREAL0000000001", "T0006", "25.00", iso(now - timedelta(hours=6)), custom="donation:1"),
                transaction(
                    "PAYOUT00000000001", "T0001", "-300.00", iso(now - timedelta(hours=5)), custom=f"case-{case_id}"
                ),
                transaction("PAYOUT00000000002", "T0001", "-75.00", iso(now - timedelta(hours=4)), custom="case-9999"),
                transaction("STRANGER000000001", "T0006", "60.00", iso(now - timedelta(hours=3))),
                transaction("HOLD0000000000001", "T1503", "-300.00", iso(now - timedelta(hours=5))),
                transaction(
                    "REFUND00000000001", "T1107", "-25.00", iso(now - timedelta(hours=2)), ref="CAPREAL0000000001"
                ),
            ],
            refreshed=refreshed,
        ),
    )
    body = client.get("/command/books/reconcile", headers=sam).json()
    by_id = {line["paypal_id"]: line for line in body["lines"] if line["paypal_id"]}
    assert by_id["CAPREAL0000000001"]["status"] == "matched"
    assert by_id["PAYOUT00000000001"]["status"] == "matched" and "case" in by_id["PAYOUT00000000001"]["hearthline"]
    assert by_id["PAYOUT00000000002"]["status"] == "not_in_books"  # a payout nobody approved
    assert by_id["STRANGER000000001"]["status"] == "not_in_books"
    assert by_id["HOLD0000000000001"]["status"] == "info"
    assert (
        by_id["REFUND00000000001"]["status"] == "matched"
        and "Refund of gift" in by_id["REFUND00000000001"]["hearthline"]
    )
    ours = [line for line in body["lines"] if not line["paypal_id"]]
    statuses = {line["hearthline"].split(" (")[0].split(":")[0]: line["status"] for line in ours}
    if milestone_id:
        assert statuses[f"Contractor milestone #{milestone_id}"] == "missing_at_paypal"
    assert any(line["status"] == "waiting" for line in ours) or tranche is None
    assert not any("CAPOLD" in str(line) or "DEMO" in str(line) for line in body["lines"])
    assert body["counts"]["not_in_books"] == 2
    assert body["start"].startswith(iso(now - timedelta(days=2))[:13])  # from when the books opened
    query = paypal_reporting.calls(TRANSACTIONS_PATH)[0]
    assert query["fields"] == ["transaction_info"] and query["balance_affecting_records_only"] == ["Y"]


def test_every_page_is_read(paypal_reporting):
    pages = {
        "1": transactions_body(
            [transaction("A0000000000000001", "T1503", "-1.00", "2026-10-19T08:00:00Z")],
            refreshed="2026-10-19T09:00:00Z",
            pages=2,
        ),
        "2": transactions_body(
            [transaction("A0000000000000002", "T1105", "1.00", "2026-10-19T08:05:00Z")],
            refreshed="2026-10-19T09:00:00Z",
            page=2,
            pages=2,
        ),
    }

    def paged(request):
        from urllib.parse import parse_qs, urlparse

        return json_response(200, pages[parse_qs(urlparse(request.url).query)["page"][0]])

    paypal_reporting.routes[TRANSACTIONS_PATH] = paged
    found, refreshed = reporting.transactions(datetime(2026, 10, 1, tzinfo=UTC), datetime(2026, 10, 19, tzinfo=UTC))
    assert [t.id for t in found] == ["A0000000000000001", "A0000000000000002"]
    assert [q["page"] for q in paypal_reporting.calls(TRANSACTIONS_PATH)] == [["1"], ["2"]]
    assert refreshed == datetime(2026, 10, 19, 9, tzinfo=UTC)


def test_batch_preview_says_whether_paypal_can_cover_it(paypal_reporting):
    sam = login_as("Sam Whitfield")
    from app.seed_command import seed_command_center

    with SessionLocal() as db:
        seed_command_center(db)
    rule = {
        "filter_model": {"damage_level": {"filterType": "set", "values": ["destroyed"]}},
        "amounts": {"destroyed": "500"},
    }
    paypal_reporting.routes[BALANCES_PATH] = json_response(200, balances_body("193.48"))
    preview = client.post("/command/batches/preview", json=rule, headers=sam).json()
    assert preview["households"] > 0
    assert preview["paypal_balance"] == {
        "available": "193.48",
        "as_of": "2026-10-19T09:00:00+00:00",
        "covers": False,
        "error": None,
    }


def test_a_window_newer_than_paypals_report_is_waiting_not_an_error(paypal_reporting):
    """After a reset the books open "now", before PayPal's latest report; PayPal answers 404 for that window."""
    sam = login_as("Sam Whitfield")
    now = datetime.now(UTC)
    with SessionLocal() as db:
        audit.record(db, action="demo.seeded", subject_type="demo", subject_id="test")
        db.query(AuditEvent).filter_by(action="demo.seeded").update({"created_at": now - timedelta(minutes=30)})
        reg = db.query(Registry).filter_by(slug="rivera-family").one()
        db.add(
            Donation(
                registry_id=reg.id,
                amount=D("25.00"),
                status="captured",
                paypal_order_id="O-NEW",
                paypal_capture_id="CAPNEW00000000001",
                captured_at=now - timedelta(minutes=5),
            )
        )
        db.commit()
    not_yet = {"name": "INVALID_REQUEST", "message": "Data for the given start date is not available.", "debug_id": "x"}
    paypal_reporting.routes[TRANSACTIONS_PATH] = json_response(404, not_yet)
    body = client.get("/command/books/reconcile", headers=sam).json()
    assert [line["status"] for line in body["lines"]] == ["waiting"]
    assert body["paypal_refreshed_at"] is None

    paypal_reporting.routes[TRANSACTIONS_PATH] = json_response(404, {"name": "RESOURCE_NOT_FOUND", "message": "x"})
    assert client.get("/command/books/reconcile", headers=sam).status_code == 400  # any other 404 is still an error


def test_staff_can_check_the_audit_chain():
    from app import audit
    from app.db import SessionLocal
    from app.models import AuditEvent
    from tests.helpers import client, login_as

    with SessionLocal() as db:
        for i in range(3):
            audit.record(db, action="test.event", subject_type="test", subject_id=i, data={"n": i})
        db.commit()
    sam = login_as("Sam Whitfield")
    ok = client.get("/command/books/audit", headers=sam).json()
    assert ok["intact"] and ok["events"] >= 3 and len(ok["latest_hash"]) == 64
    with SessionLocal() as db:  # someone edits history
        first = db.query(AuditEvent).order_by(AuditEvent.id).first()
        first.data = {"n": 99}
        db.commit()
        first_id = first.id
    bad = client.get("/command/books/audit", headers=sam).json()
    assert not bad["intact"] and bad["first_broken_id"] == first_id
    assert client.get("/command/books/audit", headers=login_as("Elena Rivera")).status_code == 403
