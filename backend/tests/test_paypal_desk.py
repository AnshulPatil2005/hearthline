import json
from types import SimpleNamespace

import pytest

from app import ai
from app.agents import paypal_desk
from app.db import SessionLocal
from app.models import AuditEvent
from tests.helpers import client, login_as

PAYPAL_TOOLS = ["get_dispute", "list_disputes", "show_subscription_details", "create_refund", "accept_dispute_claim"]


class FakePayPal:
    """Stands in for PayPal's MCP server: lists some tools (read and write) and records calls."""

    def __init__(self):
        self.calls = []

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(name=n, description=f"{n} on PayPal", input_schema={"type": "object", "properties": {}})
                for n in PAYPAL_TOOLS
            ]
        )

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        body = {"dispute_id": arguments.get("dispute_id"), "status": "UNDER_REVIEW"}
        text = SimpleNamespace(text=json.dumps(body))
        return SimpleNamespace(structured_content=None, is_error=False, content=[text])


class Turn:
    """An assistant message as the OpenAI client returns it."""

    def __init__(self, content=None, calls=()):
        self.content = content
        self.tool_calls = [
            SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name=name, arguments=json.dumps(args)))
            for i, (name, args) in enumerate(calls)
        ] or None

    def model_dump(self, exclude_none=True):
        return {"role": "assistant", "content": self.content}


@pytest.fixture
def script(monkeypatch):
    """Scripted model turns; records the tools it was offered and what it was told."""
    seen = {"tools": None, "messages": []}
    turns = []

    def chat(messages, *, tools=None, max_tokens=1500):
        seen["tools"] = [t["function"]["name"] for t in tools]
        seen["messages"] = list(messages)
        return turns.pop(0)

    monkeypatch.setattr(ai, "chat", chat)
    return turns, seen


def sam():
    login_as("Sam Whitfield")
    with SessionLocal() as db:
        from app.models import User

        return db.query(User).filter_by(name="Sam Whitfield").one().id


def ask(question):
    from app.models import User

    paypal = FakePayPal()
    with SessionLocal() as db:
        user = db.get(User, sam())
        return paypal_desk.ask(db, question, user, paypal=paypal), paypal


def test_agent_gets_only_read_tools_and_every_paypal_read_is_audited(script):
    turns, seen = script
    turns += [
        Turn(calls=[("hearthline_records", {"search": "Moreno"}), ("get_dispute", {"dispute_id": "PP-D-123"})]),
        Turn(content="PayPal shows dispute PP-D-123 under review."),
    ]
    answer, paypal = ask("What's happening with dispute PP-D-123?")
    assert answer.answer == "PayPal shows dispute PP-D-123 under review."
    assert seen["tools"] == ["hearthline_records", "get_dispute", "list_disputes", "show_subscription_details"]
    assert paypal.calls == [("get_dispute", {"dispute_id": "PP-D-123"})]
    assert [(s.tool, s.source, s.ok) for s in answer.steps] == [
        ("hearthline_records", "hearthline", True),
        ("get_dispute", "paypal", True),
    ]
    tool_results = [m["content"] for m in seen["messages"] if m.get("role") == "tool"]
    assert "UNDER_REVIEW" in tool_results[1]
    with SessionLocal() as db:
        logged = db.query(AuditEvent).filter_by(action="paypal_agent.read").one()
        assert logged.subject_id == "get_dispute" and logged.data["args"] == {"dispute_id": "PP-D-123"}


def test_money_moving_tools_are_refused_even_if_the_model_asks(script):
    turns, seen = script
    turns += [
        Turn(calls=[("create_refund", {"capture_id": "CAP-1"}), ("accept_dispute_claim", {"dispute_id": "PP-D-1"})]),
        Turn(content="I can't refund; use the Disputes desk."),
    ]
    answer, paypal = ask("Refund capture CAP-1")
    assert paypal.calls == []
    assert [(s.tool, s.ok) for s in answer.steps] == [("create_refund", False), ("accept_dispute_claim", False)]
    assert all(m["content"].startswith("Refused") for m in seen["messages"] if m.get("role") == "tool")


def test_demo_ids_never_reach_paypal(script):
    turns, _ = script
    turns += [Turn(calls=[("get_dispute", {"dispute_id": "PP-D-DEMO-1001"})]), Turn(content="That is demo data.")]
    answer, paypal = ask("Look up PP-D-DEMO-1001")
    assert paypal.calls == [] and answer.steps[0].summary.startswith("Skipped")


def test_lookup_finds_paypal_ids_in_hearthline_records():
    from decimal import Decimal

    from app.models import Donation, Registry

    login_as("Sam Whitfield")
    with SessionLocal() as db:
        reg = db.query(Registry).filter_by(slug="rivera-family").one()
        db.add(
            Donation(
                registry_id=reg.id,
                donor_name="Jordan",
                amount=Decimal("75.00"),
                status="captured",
                paypal_order_id="O-77",
                paypal_capture_id="CAP-77",
            )
        )
        db.commit()
        found = paypal_desk.lookup(db, "jordan")
        nothing = paypal_desk.lookup(db, "Nobody-by-this-name")
    assert found == {
        "donations": [
            {"donor": "Jordan", "amount": "75.00", "status": "captured", "order_id": "O-77", "capture_id": "CAP-77"}
        ]
    }
    assert nothing == {"found": "nothing matches"}


def test_ask_paypal_endpoint(script, monkeypatch):
    turns, _ = script
    turns += [Turn(content="No open disputes in PayPal.")]
    fake = FakePayPal()

    async def with_fake(db, question, user):
        return await paypal_desk._run(db, question, user, fake)

    monkeypatch.setattr(paypal_desk, "_with_paypal", with_fake)
    monkeypatch.setattr(ai, "configured", lambda: True)
    household = login_as("Elena Rivera")
    assert client.post("/command/paypal/ask", json={"question": "Open disputes?"}, headers=household).status_code == 403
    staff = login_as("Sam Whitfield")
    r = client.post("/command/paypal/ask", json={"question": "Open disputes?"}, headers=staff)
    assert r.json() == {"answer": "No open disputes in PayPal.", "steps": []}

    def busy(*a, **k):
        raise ai.AIError("busy")

    monkeypatch.setattr(ai, "chat", busy)
    r = client.post("/command/paypal/ask", json={"question": "Open disputes?"}, headers=staff)
    assert r.status_code == 503
