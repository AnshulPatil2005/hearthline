import httpx
import pytest

from app import alerts
from tests.helpers import client, login_as

NWS_FEATURE = {
    "properties": {
        "id": "urn:oid:2.49.0.1.840.0.test",
        "event": "Red Flag Warning",
        "headline": "Red Flag Warning issued for the Sierra foothills",
        "severity": "Severe",
        "description": "Gusty winds and low humidity.",
        "instruction": "Avoid outdoor burning.",
        "effective": "2026-10-07T10:00:00-07:00",
        "expires": "2099-10-08T20:00:00-07:00",
    }
}


@pytest.fixture(autouse=True)
def reset_cache():
    alerts._last_fetch.clear()


def fake_nws(monkeypatch, features):
    calls = []

    def get(url, params, headers, timeout):
        calls.append(params)
        return httpx.Response(200, json={"features": features}, request=httpx.Request("GET", url))

    monkeypatch.setattr(alerts.httpx, "get", get)
    return calls


def test_nws_alerts_are_stored_once_and_cached(monkeypatch):
    calls = fake_nws(monkeypatch, [NWS_FEATURE])
    h = login_as("Elena Rivera")
    first = client.get("/households/me/alerts", headers=h).json()
    assert [a["event"] for a in first] == ["Red Flag Warning"]
    assert calls[0]["point"] == "38.7090,-120.6270"

    alerts._last_fetch.clear()  # force another NWS call: the same alert must not be duplicated
    assert len(client.get("/households/me/alerts", headers=h).json()) == 1
    client.get("/households/me/alerts", headers=h)  # cached: no new call
    assert len(calls) == 2


def test_weather_service_outage_does_not_break_the_dashboard(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(alerts.httpx, "get", boom)
    r = client.get("/households/me/alerts", headers=login_as("Elena Rivera"))
    assert r.status_code == 200 and r.json() == []


def test_simulate_then_dismiss(monkeypatch):
    fake_nws(monkeypatch, [])
    h = login_as("Elena Rivera")
    created = client.post("/households/me/alerts/simulate", headers=h).json()
    assert created["event"] == "Evacuation Warning" and "Sablewood Fire" in created["headline"]
    assert [a["id"] for a in client.get("/households/me/alerts", headers=h).json()] == [created["id"]]

    assert client.post(f"/alerts/{created['id']}/dismiss", headers=h).status_code == 204
    assert client.get("/households/me/alerts", headers=h).json() == []
    assert client.post(f"/alerts/{created['id']}/dismiss", headers=login_as("Marcus Chen")).status_code == 404
