"""Requests that used to crash with a 500 or slip past a check: each now gets a clear 4xx and changes nothing."""

from datetime import UTC, datetime, timedelta

import pytest

from app import review
from app.agents import sentinel, shopper
from app.agents.sentinel import SentinelNote
from app.db import SessionLocal
from app.models import Case
from tests.helpers import client, login_as
from tests.test_calendar import medium_risk_case

REVIEWERS = ("Priya Nair", "Tom Becker")


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(
        sentinel, "explain", lambda facts, flags: SentinelNote(summary="s", questions=[], recommendation="approve")
    )
    monkeypatch.setattr(review, "AUDIT_RATE", 0.0)


def test_a_null_for_a_required_field_is_refused():
    h = login_as("Elena Rivera")
    item_id = client.post("/households/me/items", headers=h, json={"name": "Lamp", "unit_price": "40"}).json()["id"]
    assert client.patch(f"/items/{item_id}", headers=h, json={"name": None}).status_code == 422
    assert (
        client.patch(f"/items/{item_id}", headers=h, json={"unit_price": None}).status_code == 200
    )  # unpriced is fine
    assert client.patch("/households/me", headers=h, json={"address_line": None}).status_code == 422


def test_values_longer_than_their_column_are_refused():
    """SQLite ignores column lengths; Postgres, which production runs, failed the commit with a 500."""
    h = login_as("Elena Rivera")
    assert client.patch("/households/me", headers=h, json={"state": "California"}).status_code == 422
    assert (
        client.post("/households/me/items", headers=h, json={"name": "Lamp", "category": "x" * 61}).status_code == 422
    )


def test_malformed_input_gets_a_4xx():
    sam = login_as("Sam Whitfield")
    assert client.post("/webhooks/paypal", content=b"not json").status_code == 400
    assert client.post("/command/households/rows", headers=sam, json={"startRow": "abc"}).status_code == 422
    case_id, reviewer = medium_risk_case()
    r = login_as(reviewer)
    bad = {"events": {"updated": [{"startDate": "2026-10-20T15:00:00Z"}]}}  # no id
    assert client.post("/bryntum/calendar/sync", headers=r, json=bad).status_code == 422


def test_a_cancelled_call_cant_count_as_the_video_check():
    case_id, reviewer = medium_risk_case()
    r = login_as(reviewer)
    when = (datetime.now(UTC) + timedelta(days=1)).replace(microsecond=0)
    call = client.post(f"/review/cases/{case_id}/appointments", headers=r, json={"starts_at": when.isoformat()}).json()
    client.post("/bryntum/calendar/sync", headers=r, json={"events": {"removed": [{"id": call["id"]}]}})
    assert client.post(f"/review/appointments/{call['id']}/complete", headers=r).status_code == 409
    assert client.post(f"/review/cases/{case_id}/decision", headers=r, json={"decision": "approve"}).status_code == 409


def test_a_reviewer_who_isnt_on_the_case_cant_see_its_calls():
    case_id, reviewer = medium_risk_case()
    other = next(name for name in REVIEWERS if name != reviewer)
    with SessionLocal() as db:
        assert other not in {a.reviewer.name for a in db.get(Case, case_id).assignments}
    assert client.get(f"/review/cases/{case_id}/appointments", headers=login_as(other)).status_code == 404
    assert client.get(f"/review/cases/{case_id}/appointments", headers=login_as(reviewer)).status_code == 200


def test_too_few_reviewers_is_a_409_not_a_crash(monkeypatch):
    def no_one(*args, **kwargs):
        raise review.ReviewError("Not enough eligible reviewers")

    monkeypatch.setattr(review, "open_case", no_one)
    from tests.test_review import headers_for, new_household

    ids = new_household("Nguyen household", 38.71, -120.63, "nguyen@demo.hearthline.app")
    r = client.post("/households/me/registry", headers=headers_for(ids["user_id"]), json={"title": "Help the Nguyens"})
    assert r.status_code == 409 and "reviewers" in r.json()["detail"]


def test_shop_now_when_the_product_search_is_down(monkeypatch):
    from tests.test_shopping import fund

    def down(query, budget):
        raise ConnectionError("Channel3 unreachable")

    monkeypatch.setattr(shopper, "find_candidates", down)
    fund("Steel-toe work boots")  # the background Shopper is off in tests
    h = login_as("Elena Rivera")
    item = next(
        i for i in client.get("/households/me/registry", headers=h).json()["items"] if i["name"].startswith("Steel")
    )
    r = client.post(f"/households/me/registry/items/{item['id']}/shop", headers=h)
    assert r.status_code == 409 and "product search" in r.json()["detail"]
