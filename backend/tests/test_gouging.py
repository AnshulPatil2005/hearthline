from datetime import UTC, date, datetime, timedelta
from decimal import Decimal as D

import pytest

from app import gouging, seed_prices
from app.db import SessionLocal
from app.models import DisasterEvent, PriceWatch
from tests.helpers import client, login_as
from tests.test_shopping import fakes, fund  # noqa: F401  (fixture and helper reused)

DECLARED = datetime(2026, 9, 12, 18, tzinfo=UTC)


def days(*pairs) -> list[tuple[date, D]]:
    """(days relative to the declaration, price) -> dated history."""
    return [(DECLARED.date() + timedelta(days=d), D(p)) for d, p in pairs]


def test_judge_uses_the_median_before_the_declaration():
    history = days((-20, "100"), (-10, "100"), (-3, "80"), (-1, "100"), (2, "125"))  # one sale day before
    verdict = gouging.judge(history, DECLARED)
    assert verdict.baseline == D("100.00") and verdict.markup_percent == 25.0 and verdict.gouging
    assert gouging.judge(days((-5, "100"), (3, "110")), DECLARED).status == "ok"  # exactly +10% is allowed
    assert gouging.judge(days((-5, "100"), (3, "110.01")), DECLARED).gouging
    assert gouging.judge(days((-40, "100"), (3, "300")), DECLARED).status == "no_baseline"  # too old to count
    assert gouging.judge(days((-5, "100")), DECLARED, current=D("104.00")).status == "ok"


def test_protection_window():
    event = DisasterEvent(declared_at=DECLARED, price_protection_until=None)
    assert gouging.protection_active(event, DECLARED + timedelta(days=29))
    assert not gouging.protection_active(event, DECLARED + timedelta(days=31))  # the state's 30 days
    event.price_protection_until = DECLARED + timedelta(days=180)  # extended locally
    assert gouging.protection_active(event, DECLARED + timedelta(days=90))


def test_the_shopper_refuses_a_gouging_seller(fakes, monkeypatch):  # noqa: F811
    with SessionLocal() as db:
        login_as("Elena Rivera")
        declared = db.query(DisasterEvent).one().declared_at
    before = (gouging._aware(declared) - timedelta(days=10)).date()
    # The Home Depot boots cost $89.99 before the fire and $129.99 now (+44%); the others haven't moved.
    histories = {"p1": [(before, D("89.99"))], "p2": [(before, D("89.00"))], "p3": [(before, D("135.00"))]}
    monkeypatch.setattr(gouging, "_channel3_history", lambda pid, days: histories.get(pid, []))
    fund("Steel-toe work boots")
    p = client.get("/households/me/purchases", headers=login_as("Elena Rivera")).json()[0]
    assert [r["retailer"] for r in p["refused_offers"]] == ["homedepot.com"]
    assert p["refused_offers"][0]["markup_percent"] == 44.4
    assert p["retailer"] != "homedepot.com" and p["status"] == "paid"
    rule = next(c for c in p["policy_checks"] if c["rule"] == "no_price_gouging")
    assert rule["passed"] and "Penal Code 396" in rule["detail"]
    watch = client.get("/price-watch").json()
    assert {(r["seller"], r["status"]) for r in watch["rows"]} >= {("homedepot.com", "gouging"), ("walmart.com", "ok")}


def test_when_every_offer_is_gouging_nothing_is_bought(fakes, monkeypatch):  # noqa: F811
    with SessionLocal() as db:
        login_as("Elena Rivera")
        declared = db.query(DisasterEvent).one().declared_at
    before = (gouging._aware(declared) - timedelta(days=5)).date()
    monkeypatch.setattr(gouging, "_channel3_history", lambda pid, days: [(before, D("50.00"))])
    fund("Steel-toe work boots")
    p = client.get("/households/me/purchases", headers=login_as("Elena Rivera")).json()[0]
    assert p["status"] == "failed" and "price gouging" in p["error"] and len(p["refused_offers"]) == 3
    assert fakes == []  # nobody was paid


def test_local_survey_seed_and_public_report():
    login_as("Elena Rivera")
    with SessionLocal() as db:
        seed_prices.seed_price_watch(db)
        statuses = {(w.seller, w.title): w.status for w in db.query(PriceWatch)}
    assert statuses[("Pine Hollow Market", "Bottled water, 24 x 16.9 oz")] == "gouging"
    assert statuses[("Foothill Hardware", "Portable generator, 4,500 W")] == "ok"
    report = client.get("/price-watch").json()
    assert report["event"]["protection_active"] and report["event"]["limit_percent"] == 10.0
    water = next(r for r in report["rows"] if r["seller"] == "Pine Hollow Market" and r["category"] == "water")
    assert water["markup_percent"] > 100 and len(water["history"]) > 30


@pytest.mark.parametrize("name", ["Priya Nair", "Elena Rivera"])
def test_only_org_staff_refresh_prices(name):
    assert client.post("/command/price-watch/refresh", headers=login_as(name)).status_code == 403
    assert client.post("/command/price-watch/refresh", headers=login_as("Sam Whitfield")).json() == {"refreshed": 0}
