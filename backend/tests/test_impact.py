from decimal import Decimal as D

import pytest

from app import ai, impact, seed_command, seed_giving, seed_reopen
from app.db import SessionLocal
from tests.helpers import client, login_as


@pytest.fixture(autouse=True)
def no_ai(monkeypatch):
    """Impact text falls back to the template; the AI path is the same call other agents use."""
    impact._cache.clear()

    def down(*a, **k):
        raise ai.AIError("no model in tests")

    monkeypatch.setattr(ai, "parse", down)


@pytest.fixture
def town(monkeypatch):
    login_as("Marcus Chen")
    monkeypatch.setattr(seed_command, "COUNT", 40)
    with SessionLocal() as db:
        seed_command.seed_command_center(db)
        seed_reopen.seed_reopen_demo(db)
        seed_giving.seed_giving_demo(db)


def test_a_donor_sees_where_each_gift_went(town):
    g = client.get("/donors/me/giving", headers=login_as("Marcus Chen")).json()
    assert D(g["total_given"]) == D("308.00")  # $158 jackets + $100 laptop + $50 gift card
    assert g["families_helped"] == 1 and g["businesses_helped"] == 1 and g["items_delivered"] == 1
    jackets = next(x for x in g["gifts"] if x["item"] == "Winter jackets for the kids")
    events = [e["event"] for e in jackets["timeline"]]
    assert events[0] == "Gift prepared" and "Bought from target.com for $149.98" in events
    assert events[-1] == "Delivered to the family"
    card = next(x for x in g["gifts"] if x["kind"] == "gift_card")
    assert card["to"] == "Moreno's Bakery" and any("Replace the ovens" in e["event"] for e in card["timeline"])
    assert g["summary"].startswith("You've given $308.00") and g["summary_by_ai"] is False
    note = client.get("/donors/me/giving/note", headers=login_as("Marcus Chen")).json()
    assert note == {"summary": g["summary"], "by_ai": False}  # no model in tests: the template


def test_someone_who_hasnt_given_sees_an_empty_page(town):
    g = client.get("/donors/me/giving", headers=login_as("Elena Rivera")).json()
    assert g["gifts"] == [] and D(g["total_given"]) == 0


def test_grant_report_numbers_and_pdf(town):
    sam = login_as("Sam Whitfield")
    report = client.get("/command/reports/grant", headers=sam).json()
    n = report["numbers"]
    assert n["households_registered"] == 41 and n["registry_gifts"] == 2 and n["items_delivered"] == 1
    assert D(n["reopen_released_to_businesses"]) == D("7000.00") + D("1000.00")  # bakery ovens + outfitter lease
    assert "fictional demo data" in report["narrative"]["paragraphs"][-1]
    pdf = client.get("/command/reports/grant.pdf", headers=sam)
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 2000 and "attachment" in pdf.headers["content-disposition"]
    assert client.get("/command/reports/grant.pdf", headers=login_as("Priya Nair")).status_code == 403
