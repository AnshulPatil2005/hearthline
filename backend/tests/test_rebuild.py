from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app import ledger, rebuild, review
from app.agents import sentinel, site
from app.agents.sentinel import SentinelNote
from app.agents.site import SiteCheck
from app.db import SessionLocal
from app.models import Case, Contractor, Household
from app.paypal import payouts
from tests.helpers import client, login_as

START = datetime(2026, 10, 12, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    paid = []

    def send(payments, batch_id, subject):
        paid.append(payments[0][:2])
        return payouts.PayoutResult(batch_id=f"BATCH-{len(paid)}", status="PENDING")

    monkeypatch.setattr(payouts, "send_payouts", send)
    monkeypatch.setattr(
        site,
        "check",
        lambda title, done, jpegs: SiteCheck(
            verdict="matches", confidence=0.92, observations=["Debris removed"], concerns=[]
        ),
    )
    monkeypatch.setattr(
        sentinel, "explain", lambda facts, flags: SentinelNote(summary="s", questions=[], recommendation="approve")
    )
    monkeypatch.setattr(review, "AUDIT_RATE", 0.0)
    return paid


def fund_household(amount: str) -> int:
    login_as("Elena Rivera")
    with SessionLocal() as db:
        hid = db.query(Household).filter_by(name="Rivera household").one().id
        ledger.post(
            db,
            kind="insurance_payment",
            description="Insurance dwelling advance",
            household_id=hid,
            paypal_ref=f"INS-{amount}",
            meta={},
            lines={ledger.CASH: D(amount), ledger.household_fund(hid): -D(amount)},
        )
        db.commit()
        return hid


def plan(*milestones):
    return {
        "milestones": [
            {
                "title": t,
                "amount": a,
                "is_deposit": dep,
                "done_looks_like": f"{t} finished",
                "start_date": (START + timedelta(days=7 * i)).isoformat(),
                "end_date": (START + timedelta(days=7 * i + 6)).isoformat(),
            }
            for i, (t, a, dep) in enumerate(milestones)
        ]
    }


def new_project(h) -> dict:
    with SessionLocal() as db:
        cid = db.query(Contractor).one().id
    return client.post(
        "/households/me/projects", headers=h, json={"contractor_id": cid, "title": "Rebuild kitchen"}
    ).json()


def test_deposit_is_capped_by_california_law():
    h = login_as("Elena Rivera")
    project = new_project(h)
    dana = login_as("Dana Okafor")
    too_big = client.put(
        f"/projects/{project['id']}/plan",
        headers=dana,
        json=plan(("Deposit", "2000", True), ("Demolition", "46000", False)),
    )
    assert too_big.status_code == 409 and "1000.00" in too_big.json()["detail"]
    ok = client.put(
        f"/projects/{project['id']}/plan",
        headers=dana,
        json=plan(("Deposit", "1000", True), ("Demolition", "47000", False)),
    ).json()
    assert ok["status"] == "plan_submitted" and ok["deposit_cap"] == "1000.00" and ok["total_price"] == "48000.00"


def test_escrow_milestones_and_human_review_for_large_payments(fakes):
    hid = fund_household("25000")
    h = login_as("Elena Rivera")
    project = new_project(h)
    dana = login_as("Dana Okafor")
    client.put(
        f"/projects/{project['id']}/plan",
        headers=dana,
        json=plan(("Deposit", "1000", True), ("Demolition", "6000", False), ("Framing", "12000", False)),
    )
    accepted = client.post(f"/projects/{project['id']}/accept", headers=h).json()
    assert accepted["status"] == "active" and accepted["escrow_balance"] == "19000.00"
    with SessionLocal() as db:
        assert ledger.household_available(db, hid) == D("6000.00")  # 25,000 - 19,000 locked in escrow

    deposit, demolition, framing = accepted["milestones"]
    assert client.post(f"/milestones/{deposit['id']}/submit", headers=dana).json()["status"] == "submitted"
    assert client.post(f"/milestones/{deposit['id']}/approve", headers=h).json()["status"] == "paid"

    photo = [("files", ("site.jpg", open_test_jpeg(START + timedelta(days=10)), "image/jpeg"))]  # during demolition
    submitted = client.post(f"/milestones/{demolition['id']}/submit", headers=dana, files=photo).json()
    assert submitted["site_check"]["verdict"] == "matches" and len(submitted["photo_urls"]) == 1
    assert submitted["needs_human_review"] is False
    assert client.post(f"/milestones/{demolition['id']}/approve", headers=h).json()["status"] == "paid"

    framing_photo = [("files", ("frame.jpg", open_test_jpeg(START + timedelta(days=17)), "image/jpeg"))]
    assert client.post(f"/milestones/{framing['id']}/submit", headers=dana, files=framing_photo).json()[
        "needs_human_review"
    ]
    under_review = client.post(f"/milestones/{framing['id']}/approve", headers=h).json()
    assert under_review["status"] == "under_review"  # over $10,000: two humans must agree
    assert [p[1] for p in fakes] == [D("1000.00"), D("6000.00")]
    with SessionLocal() as db:
        case = db.get(Case, under_review["case_id"])
        reviewers = [a.reviewer.name for a in case.assignments]
    assert case.kind == "milestone_payment" and len(reviewers) == 2
    detail = client.get(f"/review/cases/{case.id}", headers=login_as(reviewers[0])).json()
    assert detail["milestone"]["title"] == "Framing" and len(detail["milestone"]["photo_urls"]) == 1
    assert detail["milestone"]["site_check"]["verdict"] == "matches"
    assert detail["photos"] == []  # site photos aren't mixed into the family's own evidence
    for name in reviewers:
        r = client.post(f"/review/cases/{case.id}/decision", headers=login_as(name), json={"decision": "approve"})
        assert r.status_code == 200, r.json()

    done = client.get(f"/projects/{project['id']}", headers=h).json()
    assert done["status"] == "completed" and done["escrow_balance"] == "0.00"
    assert fakes[-1] == ("dana.okafor@business.example.com", D("12000.00"))


def test_homeowner_wins_a_dispute_and_gets_the_money_back(fakes):
    hid = fund_household("10000")
    h = login_as("Elena Rivera")
    project = new_project(h)
    dana = login_as("Dana Okafor")
    client.put(f"/projects/{project['id']}/plan", headers=dana, json=plan(("Demolition", "6000", False)))
    milestone = client.post(f"/projects/{project['id']}/accept", headers=h).json()["milestones"][0]
    client.post(
        f"/milestones/{milestone['id']}/submit",
        headers=dana,
        files=[("files", ("x.jpg", open_test_jpeg(), "image/jpeg"))],
    )
    disputed = client.post(
        f"/milestones/{milestone['id']}/dispute",
        headers=h,
        json={"reason": "Half the debris is still in the backyard."},
    ).json()
    assert disputed["status"] == "disputed"
    with SessionLocal() as db:
        reviewer = db.get(Case, disputed["case_id"]).assignments[0].reviewer.name
    client.post(
        f"/review/cases/{disputed['case_id']}/decision",
        headers=login_as(reviewer),
        json={"decision": "reject", "reason": "Photos confirm debris remains; refund the homeowner."},
    )
    with SessionLocal() as db:
        assert ledger.household_available(db, hid) == D("10000.00")
        assert rebuild.escrow_balance(db, project["id"]) == D("0.00")
    assert fakes == []  # the contractor was never paid
    assert client.get(f"/projects/{project['id']}", headers=h).json()["status"] == "completed"  # nothing left open


def test_a_plan_the_family_hasnt_accepted_cant_be_disputed(fakes):
    """No money is held for it yet, so settling a dispute would pay out or refund money that was never escrowed."""
    hid = fund_household("10000")
    h = login_as("Elena Rivera")
    project = new_project(h)
    dana = login_as("Dana Okafor")
    sent = client.put(f"/projects/{project['id']}/plan", headers=dana, json=plan(("Demolition", "6000", False))).json()
    milestone = sent["milestones"][0]
    r = client.post(f"/milestones/{milestone['id']}/dispute", headers=h, json={"reason": "Not started"})
    assert r.status_code == 409 and "hasn't been accepted" in r.json()["detail"]
    with SessionLocal() as db:
        assert ledger.household_available(db, hid) == D("10000.00")


def test_weak_photo_check_goes_to_a_human_even_for_small_amounts(monkeypatch):
    monkeypatch.setattr(
        site,
        "check",
        lambda *a: SiteCheck(verdict="partial", confidence=0.5, observations=[], concerns=["Can't see the new wiring"]),
    )
    fund_household("5000")
    h = login_as("Elena Rivera")
    project = new_project(h)
    dana = login_as("Dana Okafor")
    client.put(f"/projects/{project['id']}/plan", headers=dana, json=plan(("Electrical rough-in", "3000", False)))
    m = client.post(f"/projects/{project['id']}/accept", headers=h).json()["milestones"][0]
    client.post(
        f"/milestones/{m['id']}/submit", headers=dana, files=[("files", ("x.jpg", open_test_jpeg(), "image/jpeg"))]
    )
    assert client.post(f"/milestones/{m['id']}/approve", headers=h).json()["status"] == "under_review"


def test_strangers_cannot_see_projects():
    h = login_as("Elena Rivera")
    project = new_project(h)
    assert client.get(f"/projects/{project['id']}", headers=login_as("Marcus Chen")).status_code == 404
    assert client.get(f"/projects/{project['id']}", headers=login_as("Priya Nair")).status_code == 200


def open_test_jpeg(taken: datetime = START + timedelta(days=3)) -> bytes:
    """A phone-style photo: carries an EXIF capture date, as real site photos do."""
    import io

    from PIL import Image

    img = Image.new("RGB", (64, 48), "gray")
    exif = Image.Exif()
    exif.get_ifd(0x8769)[36867] = taken.strftime("%Y:%m:%d %H:%M:%S")  # DateTimeOriginal
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_photos_taken_before_the_milestone_started_need_a_human(fakes):
    fund_household("5000")
    h = login_as("Elena Rivera")
    project = new_project(h)
    dana = login_as("Dana Okafor")
    client.put(f"/projects/{project['id']}/plan", headers=dana, json=plan(("Demolition", "4000", False)))
    m = client.post(f"/projects/{project['id']}/accept", headers=h).json()["milestones"][0]
    old_photo = [("files", ("old.jpg", open_test_jpeg(START - timedelta(days=30)), "image/jpeg"))]
    submitted = client.post(f"/milestones/{m['id']}/submit", headers=dana, files=old_photo).json()
    assert submitted["site_check"]["metadata_concerns"] == ["1 photo(s) were taken before this milestone started"]
    assert client.post(f"/milestones/{m['id']}/approve", headers=h).json()["status"] == "under_review"


def test_gantt_load_and_contractor_only_rescheduling():
    fund_household("20000")
    h = login_as("Elena Rivera")
    project = new_project(h)
    dana = login_as("Dana Okafor")
    client.put(
        f"/projects/{project['id']}/plan",
        headers=dana,
        json=plan(("Deposit", "1000", True), ("Demolition", "6000", False), ("Framing", "12000", False)),
    )
    client.post(f"/projects/{project['id']}/accept", headers=h)

    loaded = client.get(f"/bryntum/gantt/{project['id']}/load", headers=h).json()
    root = loaded["tasks"]["rows"][0]
    steps, move_in = root["children"][:3], root["children"][3]
    assert root["name"] == "Rebuild kitchen" and [c["status"] for c in steps] == ["pending"] * 3
    # work not yet submitted is scheduled by Bryntum's engine, no earlier than planned; the accepted plan is baseline
    assert all(not c["manuallyScheduled"] and c["constraintType"] == "startnoearlierthan" for c in steps)
    assert all(c["baselines"] == [{"startDate": c["startDate"], "endDate": c["endDate"]}] for c in steps)
    assert move_in["status"] == "move_in" and move_in["duration"] == 0 and move_in["startDate"] == steps[2]["endDate"]
    assert [(d["fromTask"], d["toTask"]) for d in loaded["dependencies"]["rows"]] == [
        (steps[0]["id"], steps[1]["id"]),
        (steps[1]["id"], steps[2]["id"]),
        (steps[2]["id"], move_in["id"]),
    ]
    assert loaded["project"]["calendar"] == loaded["calendars"]["rows"][0]["id"]

    framing = steps[2]
    # a step can't be moved to start before the step it waits for ends
    early = {"tasks": {"updated": [{"id": framing["id"], "startDate": "2026-10-20T00:00:00+00:00"}]}}
    refused = client.post(f"/bryntum/gantt/{project['id']}/sync", headers=dana, json=early).json()
    assert refused["success"] is False and "can't start before Demolition ends" in refused["message"]
    moved = {"tasks": {"updated": [{"id": framing["id"], "startDate": "2026-11-02T00:00:00+00:00"}]}}
    assert client.post(f"/bryntum/gantt/{project['id']}/sync", headers=h, json=moved).json()["success"] is False
    assert client.post(f"/bryntum/gantt/{project['id']}/sync", headers=dana, json=moved).json()["success"] is True
    after = client.get(f"/projects/{project['id']}", headers=h).json()["milestones"][2]
    assert after["start_date"].startswith("2026-11-02")
    assert client.get(f"/bryntum/gantt/{project['id']}/load", headers=login_as("Marcus Chen")).status_code == 404


def test_photos_that_dont_show_the_work_make_a_high_risk_case(monkeypatch):
    monkeypatch.setattr(
        site,
        "check",
        lambda *a: SiteCheck(verdict="does_not_match", confidence=0.95, observations=["A blank wall"], concerns=[]),
    )
    fund_household("5000")
    h = login_as("Elena Rivera")
    project = new_project(h)
    dana = login_as("Dana Okafor")
    client.put(f"/projects/{project['id']}/plan", headers=dana, json=plan(("Foundation repair", "4000", False)))
    m = client.post(f"/projects/{project['id']}/accept", headers=h).json()["milestones"][0]
    client.post(
        f"/milestones/{m['id']}/submit", headers=dana, files=[("files", ("x.jpg", open_test_jpeg(), "image/jpeg"))]
    )
    case_id = client.post(f"/milestones/{m['id']}/approve", headers=h).json()["case_id"]
    with SessionLocal() as db:
        case = db.get(Case, case_id)
        assert case.risk_tier == "high" and case.required_reviews == 2
        assert [f["code"] for f in case.flags] == ["site_photos_mismatch"]
        assert case.note == ""  # the system's findings are flags, not words put in the family's mouth
