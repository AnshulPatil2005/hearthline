from app import geo
from app.db import SessionLocal
from app.models import Household, User
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


def test_a_new_address_has_to_be_proven_again(monkeypatch):
    """Verified inside the zone, then moved: the proof was for the old address, so it doesn't carry over."""
    elena = login_as("Elena Rivera")
    with SessionLocal() as db:
        home = db.get(User, int(client.get("/me", headers=elena).json()["id"])).household
        home.residence_verified, home.vouched_by_user_id = True, 1
        db.commit()
        home_id, same = home.id, home.address_line
    monkeypatch.setattr(geo, "geocode", lambda _: (38.709, -120.627))  # still inside the fire
    client.patch("/households/me", headers=elena, json={"address_line": same, "insured_contents_value": "1"})
    with SessionLocal() as db:  # the same address again isn't a move
        assert db.get(Household, home_id).residence_verified
    client.patch("/households/me", headers=elena, json={"address_line": "9 Other Rd"})
    with SessionLocal() as db:
        home = db.get(Household, home_id)
        assert not home.residence_verified and home.vouched_by_user_id is None
        assert home.verification_level == 1  # in the zone, residence not yet proven


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
