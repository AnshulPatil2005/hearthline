from datetime import timedelta
from decimal import Decimal as D

import pytest

from app import ai, claims
from app.agents import policy_agent
from app.agents.policy_agent import Coverage, Deadline, PolicyAnswer, PolicySummary, SubLimit
from app.db import SessionLocal
from app.models import DisasterEvent, Item
from app.seed_inventory import seed_rivera_inventory
from scripts import sample_policy
from tests.helpers import client, login_as

READ = PolicySummary(
    insurer="Golden Poppy Mutual Insurance Company",
    policy_number="GPM-HO3-4471-2026",
    policy_type="homeowners",
    period="Jan 15, 2026 - Jan 15, 2027",
    deductible=2500,
    contents_settlement="replacement_cost",
    extended_replacement_percent=25,
    coverages=[
        Coverage(name="Coverage A - Dwelling", kind="dwelling", limit=485000, notes="replacement cost"),
        Coverage(name="Coverage C - Personal Property", kind="contents", limit=242500, notes="replacement cost"),
        Coverage(name="Coverage D - Loss of Use", kind="loss_of_use", limit=97000, notes="24 months"),
    ],
    sub_limits=[
        SubLimit(
            what="Jewelry, watches, furs and precious stones",
            limit=2500,
            keywords=["jewelry", "ring", "necklace", "earring", "pearl", "diamond", "watch"],
            categories=["other", "clothing"],
        ),
        SubLimit(
            what="Electronic apparatus while in a motor vehicle",
            limit=1500,
            keywords=["car stereo", "dash cam", "electronic apparatus"],
            categories=["electronics"],
        ),
    ],
    deadlines=[Deadline(what="Send a signed, sworn proof of loss", days_after_loss=60, text="within 60 days")],
    plain_summary="Your home and belongings are covered at replacement cost.",
)


@pytest.fixture
def elena(monkeypatch):
    monkeypatch.setattr(policy_agent, "read", lambda text: READ)
    headers = login_as("Elena Rivera")
    with SessionLocal() as db:
        from app.models import Household

        seed_rivera_inventory(db)
        home = db.query(Household).filter_by(name="Rivera household").one()
        inventory = sum((i.total_value for i in db.query(Item).filter_by(household_id=home.id)), D(0))
        declared = db.query(DisasterEvent).one().declared_at.date()
    return headers, inventory, declared


def upload(headers, data: bytes, name="policy.pdf"):
    return client.post("/households/me/policy", headers=headers, files={"file": (name, data, "application/pdf")})


def test_the_policy_is_read_and_compared_with_the_inventory(elena):
    headers, inventory, declared = elena
    r = upload(headers, sample_policy.build())
    assert r.status_code == 201, r.text
    check = r.json()["check"]
    assert D(check["inventory_value"]) == inventory and D(check["contents_limit"]) == D("242500")
    assert D(check["contents_gap"]) == 0
    jewelry, car = check["sub_limits"]
    assert sorted(jewelry["items"]) == ["Gold wedding band and diamond necklace", "Grandmother's pearl earrings"]
    assert D(jewelry["items_value"]) == D("5150.00") and D(jewelry["over_by"]) == D("2650.00")
    assert car["items"] == []  # the TV and laptop are electronics, but not "in a motor vehicle"
    assert check["deadlines"][0]["due"] == (declared + timedelta(days=60)).isoformat()
    assert client.get("/households/me/policy", headers=headers).json()["summary"]["insurer"].startswith("Golden Poppy")


def test_files_that_arent_readable_policies_are_refused(elena):
    headers, _, _ = elena
    assert upload(headers, b"not a pdf").status_code == 422
    blank = sample_policy.FPDF()
    blank.add_page()
    assert "no readable text" in upload(headers, bytes(blank.output())).json()["detail"]


def test_when_the_agent_is_down_nothing_half_done_is_shown(elena, monkeypatch):
    headers, _, _ = elena

    def down(text):
        raise ai.AIError("busy")

    monkeypatch.setattr(policy_agent, "read", down)
    assert upload(headers, sample_policy.build()).status_code == 503
    assert client.get("/households/me/policy", headers=headers).status_code == 404


def test_questions_are_answered_from_the_policy(elena, monkeypatch):
    headers, _, _ = elena
    assert (
        client.post("/households/me/policy/ask", headers=headers, json={"question": "Is fire covered?"}).status_code
        == 404
    )
    upload(headers, sample_policy.build())
    seen = {}

    def ask(text, question):
        seen.update(text=text, question=question)
        return PolicyAnswer(
            answer="Yes, up to $2,500 for jewelry.", quote="d. $2,500 for loss of jewelry", in_policy=True
        )

    monkeypatch.setattr(policy_agent, "ask", ask)
    a = client.post("/households/me/policy/ask", headers=headers, json={"question": "How much for my necklace?"}).json()
    assert a["in_policy"] and "Golden Poppy" in seen["text"] and seen["question"] == "How much for my necklace?"


def test_word_matching():
    def item(name):
        return Item(name=name, category="other")

    assert claims.matches(item("Grandmother's pearl earrings"), ["earring"])
    assert claims.matches(item("Gold wedding band"), ["ring", "band"])
    assert not claims.matches(item("Goldware serving set"), ["gold"])  # a different kind of thing
    assert not claims.matches(item("Earring stand"), ["ear"])  # too short to trust


def test_well_known_sub_limits_match_items_whatever_keywords_the_agent_picked():
    words = claims.keywords_for("Jewelry, watches, furs, precious and semiprecious stones", ["jewelry", "stone"])
    assert claims.matches(Item(name="Gold wedding band and diamond necklace", category="other"), words)
    assert claims.matches(Item(name="Grandmother's pearl earrings", category="other"), words)
    assert not claims.matches(Item(name="65-inch 4K smart TV", category="electronics"), words)


def test_an_item_counts_under_its_best_sub_limit_only(elena):
    headers, _, _ = elena
    summary = READ.model_copy(deep=True)
    summary.sub_limits.append(
        SubLimit(what="Silverware, goldware and pewterware", limit=2500, keywords=["silverware", "gold"], categories=[])
    )
    with SessionLocal() as db:
        from app.models import Household

        home = db.query(Household).filter_by(name="Rivera household").one()
        result = claims.check(summary, home, list(db.query(Item).filter_by(household_id=home.id)))
    jewelry, _, silver = result.sub_limits
    assert "Gold wedding band and diamond necklace" in jewelry.items and silver.items == []
