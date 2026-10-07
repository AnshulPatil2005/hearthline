from app import geo
from app.seed import SABLEWOOD_FIRE_ZONE
from tests.helpers import client, login_as


def test_in_zone():
    assert geo.in_zone(SABLEWOOD_FIRE_ZONE, 38.709, -120.627)
    assert not geo.in_zone(SABLEWOOD_FIRE_ZONE, 38.80, -120.627)


def test_rivera_household_is_inside_the_fire():
    body = client.get("/households/me", headers=login_as("Elena Rivera")).json()
    assert body["disaster_event"]["slug"] == "sablewood-fire"
    assert body["in_disaster_zone"] is True


def test_update_coverage_without_geocoding(monkeypatch):
    monkeypatch.setattr(geo, "geocode", lambda _: (_ for _ in ()).throw(AssertionError("should not geocode")))
    r = client.patch("/households/me", headers=login_as("Elena Rivera"), json={"insured_contents_value": "95000"})
    assert r.status_code == 200
    assert r.json()["insured_contents_value"] == "95000.00"


def test_moving_outside_the_zone_clears_the_event(monkeypatch):
    monkeypatch.setattr(geo, "geocode", lambda _: (37.77, -122.42))
    r = client.patch("/households/me", headers=login_as("Elena Rivera"), json={"address_line": "1 Market St"})
    assert r.json()["disaster_event"] is None
    assert r.json()["in_disaster_zone"] is False


def test_unknown_address_is_rejected(monkeypatch):
    monkeypatch.setattr(geo, "geocode", lambda _: None)
    r = client.patch("/households/me", headers=login_as("Elena Rivera"), json={"address_line": "Nowhere"})
    assert r.status_code == 422


def test_non_household_user_has_no_household():
    assert client.get("/households/me", headers=login_as("Marcus Chen")).status_code == 404


def test_disasters_include_zone():
    login_as("Marcus Chen")
    events = client.get("/disasters").json()
    assert events[0]["zone"]["type"] == "Polygon"
