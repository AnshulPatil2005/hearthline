"""Real disasters: staff open a FEMA declaration or a severe NWS warning with its counties (or polygon) as the zone;
households inside join it, and first-72-hours aid is proposed for it. OpenFEMA, the NWS and TIGERweb are stubbed."""

import httpx
import pytest
from shapely.geometry import shape

from app import real_disasters
from app.db import SessionLocal
from app.models import DisasterEvent, Household, RapidAidTrigger
from tests.helpers import client, login_as

# A household in southwest Georgia, outside the fictional Sablewood Fire
LAT, LNG = 31.17, -84.73
SQUARE = {
    "type": "Polygon",
    "coordinates": [[[-85.0, 31.0], [-84.5, 31.0], [-84.5, 31.4], [-85.0, 31.4], [-85.0, 31.0]]],
}
ELSEWHERE = {
    "type": "Polygon",
    "coordinates": [[[-84.4, 31.0], [-84.0, 31.0], [-84.0, 31.4], [-84.4, 31.4], [-84.4, 31.0]]],
}
FEMA_ROWS = [
    {
        "femaDeclarationString": "DR-4999-GA",
        "disasterNumber": 4999,
        "state": "GA",
        "declarationDate": "2026-10-15T00:00:00.000Z",
        "incidentType": "Severe Storm",
        "declarationTitle": "SEVERE STORMS AND FLOODING",
        "designatedArea": area,
        "fipsStateCode": "13",
        "fipsCountyCode": county,
    }
    for area, county in [("Miller (County)", "201"), ("Seminole (County)", "253"), ("Example (Tribal Lands)", "000")]
]


def nws_alert(alert_id: str, event: str, severity: str, geometry: dict | None, same: list[str]) -> dict:
    return {
        "geometry": geometry,
        "properties": {
            "id": alert_id,
            "event": event,
            "severity": severity,
            "headline": f"{event} for southwest Georgia",
            "areaDesc": "Miller, GA; Seminole, GA",
            "sent": "2026-10-22T10:00:00-04:00",
            "expires": "2026-10-22T22:00:00-04:00",
            "geocode": {"SAME": same},
        },
    }


ALERTS = [
    nws_alert("urn:oid:2.49.0.1.840.0.evac", "Evacuation Order", "Extreme", None, ["013201", "013253"]),
    nws_alert("urn:oid:2.49.0.1.840.0.flood", "Flood Warning", "Severe", ELSEWHERE, ["013099"]),
]


class Answer:
    def __init__(self, data: dict):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


@pytest.fixture
def services(monkeypatch):
    """OpenFEMA, the NWS and the Census Bureau's county shapes, as they answer."""
    calls: list[str] = []
    real_disasters._cache.clear()

    def get(url, params=None, headers=None, timeout=None):
        calls.append(url)
        if url == real_disasters.OPENFEMA:
            wanted = params["$filter"]
            rows = FEMA_ROWS if "ge" in wanted or "4999" in wanted else []
            return Answer({"DisasterDeclarationsSummaries": rows})
        if url.startswith(real_disasters.TIGERWEB):
            assert "COUNTY IN ('201','253')" in params["where"] and params["where"].startswith("STATE='13'")
            return Answer({"features": [{"geometry": SQUARE, "properties": {}}]})
        if url == real_disasters.NWS_ALERTS:
            return Answer({"features": ALERTS})
        for alert in ALERTS:
            if url.endswith(alert["properties"]["id"]):
                return Answer(alert)
        raise AssertionError(f"unexpected call to {url}")

    monkeypatch.setattr(real_disasters.httpx, "get", get)
    return calls


def georgia_household() -> int:
    with SessionLocal() as db:
        home = Household(
            name="Okafor household",
            address_line="1 Main St",
            city="Colquitt",
            state="GA",
            postal_code="39837",
            lat=LAT,
            lng=LNG,
            verification_level=1,
        )
        db.add(home)
        db.commit()
        return home.id


def test_opening_a_fema_declaration_draws_its_counties_and_proposes_aid(services):
    sam = login_as("Sam Whitfield")
    home = georgia_household()

    [listed] = client.get("/command/disasters/fema", headers=sam).json()
    assert (listed["code"], listed["title"], listed["kind"], listed["counties"]) == (
        "DR-4999-GA",
        "Severe Storms and Flooding",
        "storm",
        2,
    )
    assert listed["unmapped"] == ["Example (Tribal Lands)"] and listed["opened_event_id"] is None

    preview = client.get("/command/disasters/fema/4999/zone", headers=sam).json()
    assert shape(preview["zone"]).equals(shape(SQUARE)) and preview["households"] == 1

    r = client.post("/command/disasters/fema/4999", headers=sam)
    assert r.status_code == 201, r.text
    event = r.json()
    assert (event["name"], event["source"], event["is_fictional"], event["households"]) == (
        "Severe Storms and Flooding (GA)",
        "fema",
        False,
        1,
    )
    assert event["opened_by"] == "Sam Whitfield"
    with SessionLocal() as db:
        assert db.get(Household, home).disaster_event_id == event["id"]
        trigger = db.query(RapidAidTrigger).filter_by(disaster_event_id=event["id"]).one()
        assert (trigger.source, trigger.event, trigger.headline) == (
            "declaration",
            "Major Disaster Declaration",
            "FEMA DR-4999-GA: Severe Storms and Flooding",
        )
        assert db.get(DisasterEvent, event["id"]).price_protection_until is None  # California's law only
    assert client.get("/command/disasters/fema", headers=sam).json()[0]["opened_event_id"] == event["id"]
    assert client.post("/command/disasters/fema/4999", headers=sam).status_code == 409  # already open

    closed = client.post(f"/command/disasters/{event['id']}/close", headers=sam).json()
    assert closed["status"] == "closed"
    with SessionLocal() as db:  # its waiting proposal is dismissed: nothing is paid for a closed disaster
        trigger = db.query(RapidAidTrigger).filter_by(disaster_event_id=event["id"]).one()
        assert (trigger.status, trigger.note) == ("dismissed", "The disaster was closed")
    with SessionLocal() as db:
        demo = db.query(DisasterEvent).filter_by(is_fictional=True).one()
    assert client.post(f"/command/disasters/{demo.id}/close", headers=sam).status_code == 409  # the demo stays
    assert client.post("/command/disasters/fema/4999", headers=sam).status_code == 201  # opened again


def test_a_warning_without_a_polygon_takes_its_counties_and_proposes_aid(services):
    sam = login_as("Sam Whitfield")
    georgia_household()
    warnings = client.get("/command/disasters/nws", headers=sam).json()
    assert [(w["event"], w["has_shape"], w["first_72_hours"], w["kind"]) for w in warnings] == [
        ("Evacuation Order", False, True, "wildfire"),  # qualifying warnings first
        ("Flood Warning", True, False, "flood"),
    ]
    r = client.post("/command/disasters/nws", json={"alert_id": "urn:oid:2.49.0.1.840.0.evac"}, headers=sam)
    assert r.status_code == 201, r.text
    event = r.json()
    assert (event["source"], event["households"]) == ("nws", 1) and shape(event["zone"]).equals(shape(SQUARE))
    assert event["name"] == "Evacuation Order: Miller, GA"
    with SessionLocal() as db:
        [trigger] = db.query(RapidAidTrigger).filter_by(disaster_event_id=event["id"]).all()
        assert (trigger.source, trigger.external_id) == ("nws", "urn:oid:2.49.0.1.840.0.evac")


def test_a_warning_with_its_own_polygon_needs_no_county_shapes(services):
    sam = login_as("Sam Whitfield")
    preview = client.get(
        "/command/disasters/nws/zone", params={"alert_id": "urn:oid:2.49.0.1.840.0.flood"}, headers=sam
    ).json()
    assert preview == {"zone": ELSEWHERE, "households": 0}
    event = client.post("/command/disasters/nws", json={"alert_id": "urn:oid:2.49.0.1.840.0.flood"}, headers=sam)
    assert event.status_code == 201
    assert not any(url.startswith(real_disasters.TIGERWEB) for url in services)
    with SessionLocal() as db:  # a flood warning isn't one that means leaving now: no first-72-hours aid
        assert db.query(RapidAidTrigger).filter_by(disaster_event_id=event.json()["id"]).count() == 0


def test_only_org_staff_and_a_service_that_is_down(monkeypatch):
    real_disasters._cache.clear()
    assert client.get("/command/disasters/fema", headers=login_as("Elena Rivera")).status_code == 403

    def down(*args, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(real_disasters.httpx, "get", down)
    r = client.get("/command/disasters/fema", headers=login_as("Sam Whitfield"))
    assert r.status_code == 503 and "didn't answer" in r.json()["detail"]
    bad = client.get("/command/disasters/nws/zone", params={"alert_id": "x"}, headers=login_as("Sam Whitfield"))
    assert bad.status_code == 409
