from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app import review
from app.agents import sentinel
from app.agents.sentinel import SentinelNote
from app.db import SessionLocal
from app.models import Case, EvidenceLevel, Household, Item
from tests.helpers import client, login_as


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(
        sentinel, "explain", lambda facts, flags: SentinelNote(summary="s", questions=[], recommendation="approve")
    )
    monkeypatch.setattr(review, "AUDIT_RATE", 0.0)


def medium_risk_case() -> tuple[int, str]:
    """A contents claim with a costly item and no evidence: medium risk, so a video call is required."""
    h = login_as("Elena Rivera")
    with SessionLocal() as db:
        home = db.query(Household).filter_by(name="Rivera household").one()
        db.add(Item(household_id=home.id, name="Piano", unit_price=D("6000"), evidence_level=EvidenceLevel.MEMORY))
        db.commit()
    case = client.post("/households/me/cases", headers=h, json={"kind": "contents_claim"}).json()
    with SessionLocal() as db:
        reviewer = db.get(Case, case["id"]).assignments[0].reviewer.name
    return case["id"], reviewer


def test_video_call_must_be_completed_before_approval():
    case_id, reviewer = medium_risk_case()
    r = login_as(reviewer)
    approve = {"decision": "approve"}
    assert client.post(f"/review/cases/{case_id}/decision", headers=r, json=approve).status_code == 409

    when = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)
    call = client.post(f"/review/cases/{case_id}/appointments", headers=r, json={"starts_at": when.isoformat()}).json()
    assert call["status"] == "scheduled" and call["household_name"] == "Rivera household"
    assert [a["id"] for a in client.get("/households/me/appointments", headers=login_as("Elena Rivera")).json()] == [
        call["id"]
    ]

    assert client.post(f"/review/appointments/{call['id']}/complete", headers=r).json()["status"] == "completed"
    assert client.post(f"/review/cases/{case_id}/decision", headers=r, json=approve).json()["status"] == "approved"


def test_bryntum_crud_manager_load_and_sync():
    case_id, reviewer = medium_risk_case()
    r = login_as(reviewer)
    start = datetime(2026, 10, 20, 15, 0, tzinfo=UTC)
    call = client.post(f"/review/cases/{case_id}/appointments", headers=r, json={"starts_at": start.isoformat()}).json()

    loaded = client.get("/bryntum/calendar/load?requestId=7", headers=r).json()
    assert loaded["success"] and loaded["requestId"] == 7
    assert {res["name"] for res in loaded["resources"]["rows"]} >= {"Priya Nair", "Tom Becker", "Grace Alvarez"}
    event = loaded["events"]["rows"][0]
    assert event["caseId"] == case_id and event["eventColor"] == "orange"  # medium risk

    moved = (start + timedelta(hours=2)).isoformat()
    sync = client.post(
        "/bryntum/calendar/sync",
        headers=r,
        json={"requestId": 8, "events": {"updated": [{"id": call["id"], "startDate": moved}]}},
    ).json()
    assert sync["success"] and sync["events"]["rows"] == [{"id": call["id"]}]
    assert (
        client.get(f"/review/cases/{case_id}/appointments", headers=r)
        .json()[0]["starts_at"]
        .startswith("2026-10-20T17:00")
    )

    drawn = client.post("/bryntum/calendar/sync", headers=r, json={"events": {"added": [{"$PhantomId": "_g1"}]}}).json()
    assert drawn["success"] is False  # calls are booked from a case, not drawn on the calendar

    client.post("/bryntum/calendar/sync", headers=r, json={"events": {"removed": [{"id": call["id"]}]}})
    assert client.get("/bryntum/calendar/load", headers=r).json()["events"]["rows"] == []

    board = client.get("/bryntum/board/load", headers=login_as("Grace Alvarez")).json()
    assert {row["status"] for row in board["tasks"]["rows"]} == {"in_review"}
    assert client.get("/bryntum/board/load", headers=login_as("Elena Rivera")).status_code == 403
