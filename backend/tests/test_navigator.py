"""The recovery navigator: code lists the family's open steps with dates, soonest and most pressing first; the AI
(stubbed) only explains them and answers from them, once per language until the steps change."""

from datetime import timedelta
from decimal import Decimal as D

import pytest

from app import ai, navigator
from app.db import SessionLocal
from app.models import DisasterEvent, Household, InsurancePolicy, Purchase
from tests.helpers import client, login_as
from tests.test_insurance import READ

PLAN = "/households/me/navigator"


@pytest.fixture
def elena():
    return login_as("Elena Rivera")


@pytest.fixture
def ai_calls(monkeypatch):
    calls = []

    def parse(output_format, *, system, content, max_tokens=8000):
        calls.append((output_format.__name__, system, content[0]["text"]))
        if output_format is navigator.Explanation:
            return navigator.Explanation(summary=f"Plan #{len(calls)}")
        return navigator.Answer(answer="By the date in your steps.", steps=["fema_apply:event-1", "made-up"])

    monkeypatch.setattr(ai, "parse", parse)
    return calls


def rivera() -> tuple[int, int]:
    with SessionLocal() as db:
        home = db.query(Household).filter_by(name="Rivera household").one()
        return home.id, home.disaster_event_id


def keys(plan: dict) -> list[str]:
    return [s["key"] for s in plan["steps"] if not s["done"]]


def test_the_steps_come_from_where_the_family_stands(elena):
    home_id, event_id = rivera()
    with SessionLocal() as db:
        db.add(
            Purchase(
                household_id=home_id,
                title="Twin mattresses",
                retailer="Sablewood Mercantile",
                unit_price=D("150"),
                quantity=2,
                total=D("300"),
                status="awaiting_approval",
            )
        )
        db.commit()
        declared = db.get(DisasterEvent, event_id).declared_at.date()
    plan = client.get(PLAN, headers=elena).json()
    found = keys(plan)
    # waiting on the family now comes first; then dated steps; then the rest
    assert found[0] in {"verify_address", "confirm_residence", "approve_purchase", "connect_paypal"}
    assert {"approve_purchase", "fema_apply", "upload_policy"} <= set(found)
    fema = next(s for s in plan["steps"] if s["key"] == "fema_apply")
    assert fema["due"] == (declared + timedelta(days=navigator.FEMA_DAYS)).isoformat()
    assert fema["manual"] and fema["link"] == navigator.FEMA_URL
    purchase = next(s for s in plan["steps"] if s["key"] == "approve_purchase")
    assert purchase["params"]["total"] == "$300.00" and purchase["link"] == "/registry"


def test_the_policys_deadlines_become_dated_steps(elena):
    home_id, event_id = rivera()
    with SessionLocal() as db:
        db.add(
            InsurancePolicy(
                household_id=home_id, filename="policy.pdf", pdf=b"%PDF", text="...", summary=READ.model_dump()
            )
        )
        db.commit()
        declared = db.get(DisasterEvent, event_id).declared_at.date()
    plan = client.get(PLAN, headers=elena).json()
    deadline = next(s for s in plan["steps"] if s["key"] == "policy_deadline")
    assert deadline["params"]["what"] == "Send a signed, sworn proof of loss"
    assert deadline["due"] == (declared + timedelta(days=60)).isoformat()
    assert "prepare_claim" in keys(plan) and "upload_policy" not in keys(plan)


def test_the_ai_explains_once_per_language_until_the_steps_change(elena, ai_calls):
    assert client.get(PLAN, headers=elena).json()["note"] is None
    first = client.post(f"{PLAN}/explain", json={"lang": "es"}, headers=elena).json()
    again = client.post(f"{PLAN}/explain", json={"lang": "es"}, headers=elena).json()
    assert first["text"] == again["text"] == "Plan #1" and len(ai_calls) == 1
    assert "Spanish" in ai_calls[0][1] and "fema_apply" in ai_calls[0][2]  # the facts go in; the language is asked
    assert client.get(f"{PLAN}?lang=es", headers=elena).json()["note"]["text"] == "Plan #1"
    assert client.get(f"{PLAN}?lang=en", headers=elena).json()["note"] is None

    client.post(f"{PLAN}/steps/fema_apply:event-1", json={"done": True}, headers=elena)  # the steps changed
    assert client.get(f"{PLAN}?lang=es", headers=elena).json()["note"] is None  # the old explanation is stale
    assert client.post(f"{PLAN}/explain", json={"lang": "es"}, headers=elena).json()["text"] == "Plan #2"


def test_answers_only_point_at_real_steps_and_only_some_steps_are_marked_by_hand(elena, ai_calls):
    answer = client.post(f"{PLAN}/ask", json={"lang": "en", "question": "When is FEMA due?"}, headers=elena).json()
    assert answer == {"answer": "By the date in your steps.", "steps": ["fema_apply:event-1"]}
    assert client.post(f"{PLAN}/ask", json={"lang": "xx", "question": "Hello?"}, headers=elena).status_code == 422

    done = client.post(f"{PLAN}/steps/fema_apply:event-1", json={"done": True}, headers=elena).json()
    assert next(s for s in done["steps"] if s["key"] == "fema_apply")["done"] is True
    assert client.post(f"{PLAN}/steps/upload_policy", json={"done": True}, headers=elena).status_code == 409
    undone = client.post(f"{PLAN}/steps/fema_apply:event-1", json={"done": False}, headers=elena).json()
    assert next(s for s in undone["steps"] if s["key"] == "fema_apply")["done"] is False


def test_the_ai_being_down_still_shows_the_steps(elena, monkeypatch):
    def down(*args, **kwargs):
        raise ai.AIError("No AI model could answer")

    monkeypatch.setattr(ai, "parse", down)
    assert client.post(f"{PLAN}/explain", json={"lang": "en"}, headers=elena).status_code == 503
    assert client.get(PLAN, headers=elena).status_code == 200
