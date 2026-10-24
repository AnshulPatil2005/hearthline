from decimal import Decimal as D

import pytest

from app import ledger, seed_command
from app.db import SessionLocal
from app.models import Household
from tests.helpers import client, login_as

ROWS = "/command/households/rows"


@pytest.fixture
def sam(monkeypatch):
    """The org admin, with a small generated town (the real seed makes 2,000 households)."""
    headers = login_as("Sam Whitfield")
    monkeypatch.setattr(seed_command, "COUNT", 80)
    with SessionLocal() as db:
        seed_command.seed_command_center(db)
    return headers


def ask(headers, **req) -> dict:
    r = client.post(ROWS, headers=headers, json={"startRow": 0, "endRow": 100, **req})
    assert r.status_code == 200, r.text
    return r.json()


def test_rows_page_sort_and_count(sam):
    everything = ask(sam, sortModel=[{"colId": "unmet_need", "sort": "desc"}])
    assert everything["lastRow"] == 81  # 80 generated + the Rivera household from the base seed
    needs = [D(r["unmet_need"]) for r in everything["rows"]]
    assert needs == sorted(needs, reverse=True)
    page = ask(sam, startRow=20, endRow=30, sortModel=[{"colId": "unmet_need", "sort": "desc"}])
    assert [r["id"] for r in page["rows"]] == [r["id"] for r in everything["rows"][20:30]]
    assert all(len(r["help_trend"]) == 8 for r in page["rows"])


def test_help_received_comes_from_the_ledger(sam):
    with SessionLocal() as db:
        home = db.query(Household).filter_by(name="Rivera household").one()
        home.estimated_loss = D("10000")
        ledger.post(
            db,
            kind="insurance_payment",
            description="Advance",
            household_id=home.id,
            paypal_ref="T-INS",
            lines={ledger.CASH: D("3000"), ledger.household_fund(home.id): -D("3000")},
        )
        ledger.post(
            db,
            kind="payout",
            description="Cash aid",
            household_id=home.id,
            paypal_ref="T-AID",
            lines={ledger.CASH_AID: D("500"), ledger.CASH: -D("500")},
        )
        db.commit()
    row = ask(sam, filterModel={"name": {"filterType": "text", "type": "equals", "filter": "Rivera household"}})["rows"]
    assert len(row) == 1
    assert row[0]["help_received"] == "3500.00" and row[0]["unmet_need"] == "6500.00"
    assert sum(row[0]["help_trend"]) == 3500


def test_filters(sam):
    destroyed = ask(sam, filterModel={"damage_level": {"filterType": "set", "values": ["destroyed"]}})
    assert destroyed["lastRow"] > 0 and {r["damage_level"] for r in destroyed["rows"]} == {"destroyed"}

    big = ask(sam, filterModel={"unmet_need": {"filterType": "number", "type": "greaterThan", "filter": 50000}})
    assert all(D(r["unmet_need"]) > 50000 for r in big["rows"])

    both = ask(
        sam,
        filterModel={
            "damage_level": {"filterType": "set", "values": ["destroyed"]},
            "verification_level": {"filterType": "set", "values": ["2"]},
            "payout_ready": {"filterType": "set", "values": [True]},
        },
    )
    assert all(r["verification_level"] == 2 and r["payout_ready"] for r in both["rows"])

    shelter = ask(sam, filterModel={"needs": {"filterType": "set", "values": ["shelter"]}})
    assert shelter["lastRow"] > 0 and all("shelter" in r["needs"] for r in shelter["rows"])

    either = ask(
        sam,
        filterModel={
            "household_size": {
                "filterType": "number",
                "operator": "OR",
                "conditions": [{"type": "equals", "filter": 1}, {"type": "greaterThanOrEqual", "filter": 5}],
            }
        },
    )
    assert all(r["household_size"] == 1 or r["household_size"] >= 5 for r in either["rows"])


def test_grouping_and_drill_down(sam):
    total = ask(sam)["lastRow"]
    groups = ask(
        sam,
        rowGroupCols=[{"id": "street", "field": "street"}],
        valueCols=[{"id": "unmet_need", "field": "unmet_need", "aggFunc": "sum"}],
        sortModel=[{"colId": "unmet_need", "sort": "desc"}],
    )
    assert sum(g["childCount"] for g in groups["rows"]) == total == groups["matching"]
    sums = [D(g["unmet_need"]) for g in groups["rows"]]
    assert sums == sorted(sums, reverse=True)

    top = groups["rows"][0]
    inside = ask(sam, rowGroupCols=[{"id": "street", "field": "street"}], groupKeys=[top["street"]])
    assert inside["lastRow"] == top["childCount"] and {r["street"] for r in inside["rows"]} == {top["street"]}
    assert sum(D(r["unmet_need"]) for r in inside["rows"]) == D(top["unmet_need"])


def test_set_filter_values_and_summary(sam):
    damage = client.get("/command/households/values/damage_level", headers=sam).json()
    assert {"destroyed", "major", "minor", "affected"} <= set(damage)
    summary = client.get("/command/summary", headers=sam).json()
    assert summary["households"] == 81 and summary["destroyed"] > 0


def test_only_organization_staff_see_every_household(sam):
    assert client.post(ROWS, headers=login_as("Priya Nair"), json={}).status_code == 403
    assert client.post(ROWS, headers=login_as("Elena Rivera"), json={}).status_code == 403
    assert client.post(ROWS, headers=login_as("Grace Alvarez"), json={}).status_code == 200


def test_bad_requests_are_rejected(sam):
    bad = client.post(ROWS, headers=sam, json={"filterModel": {"payout_email": {"filterType": "text", "filter": "a"}}})
    assert bad.status_code == 422
    group = client.post(ROWS, headers=sam, json={"rowGroupCols": [{"id": "name", "field": "name"}]})
    assert group.status_code == 422


def test_the_live_map_shows_the_grids_households_with_what_has_a_place(sam, monkeypatch):
    from app import rapid_aid
    from app.models import DisasterEvent
    from app.paypal import payouts

    everything = client.post("/command/map", json={}, headers=sam).json()
    assert len(everything["households"]) == 81 and all(len(h) == 6 for h in everything["households"])
    assert [z["name"] for z in everything["zones"]] == ["Sablewood Fire"] and everything["paid"] == []
    only = {"damage_level": {"filterType": "set", "values": ["destroyed"]}}
    destroyed = client.post("/command/map", json={"filter_model": only}, headers=sam).json()
    assert 0 < len(destroyed["households"]) < 81 and {h[3] for h in destroyed["households"]} == {"destroyed"}
    bad = client.post("/command/map", json={"filter_model": {"nope": {"filterType": "text"}}}, headers=sam)
    assert bad.status_code == 422

    # first-72-hours aid lands on the map
    monkeypatch.setattr(payouts, "send_payouts", lambda *a, **k: payouts.PayoutResult(batch_id="B-1", status="PENDING"))
    monkeypatch.setattr(rapid_aid, "start_mandate_round", lambda: None)
    with SessionLocal() as db:
        rivera = db.query(Household).filter_by(name="Rivera household").one()
        rivera.verification_level, rivera.payout_email = 3, "elena@personal.example.com"
        fire = db.query(DisasterEvent).filter_by(status="active").one().id
        db.commit()
        rivera_id = rivera.id
    trigger = client.post("/command/rapid-aid/simulate", json={"disaster_id": fire}, headers=sam).json()["triggers"][0]
    client.post(f"/command/rapid-aid/{trigger['id']}/approve", headers=sam)
    paid = client.post("/command/map", json={}, headers=sam).json()["paid"]
    assert rivera_id in {p["household_id"] for p in paid}

    card = client.get(f"/command/map/households/{rivera_id}", headers=sam).json()
    assert (card["name"], card["damage_level"]) == ("Rivera household", "destroyed")
    assert client.get("/command/map/households/999999", headers=sam).status_code == 404
    assert client.post("/command/map", json={}, headers=login_as("Elena Rivera")).status_code == 403
