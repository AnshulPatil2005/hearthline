import time

import pytest

from app import demo_reset
from app.db import SessionLocal
from app.models import Donation, Registry, User
from app.seed import seed
from tests.helpers import client, login_as


@pytest.fixture(autouse=True)
def fresh_cooldown(monkeypatch):
    monkeypatch.setitem(demo_reset._state, "last", 0.0)
    monkeypatch.setitem(demo_reset._state, "running", False)


def light_seed():
    with SessionLocal() as db:
        seed(db)


def test_reset_wipes_changes_and_brings_the_personas_back():
    login_as("Elena Rivera")
    with SessionLocal() as db:
        elena_id = db.query(User).filter_by(name="Elena Rivera").one().id
        reg = db.query(Registry).filter_by(slug="rivera-family").one()
        db.add(Donation(registry_id=reg.id, amount=5, paypal_order_id="O-RESET", donor_name="Someone"))
        db.commit()
    demo_reset.start(reseed=light_seed, background=False)
    with SessionLocal() as db:
        assert db.query(Donation).filter_by(paypal_order_id="O-RESET").count() == 0
        assert db.query(User).filter_by(name="Elena Rivera").one().id == elena_id  # old sign-ins keep working
    assert demo_reset.status()["error"] is None


def test_reset_waits_ten_minutes_between_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(demo_reset, "wipe", lambda: calls.append("wipe"))
    monkeypatch.setattr(demo_reset, "_seed", lambda: calls.append("seed"))
    assert client.post("/demo/reset").status_code == 202
    for _ in range(100):  # the reset runs in a background thread
        if not client.get("/demo/reset").json()["running"]:
            break
        time.sleep(0.05)
    assert calls == ["wipe", "seed"]
    again = client.post("/demo/reset")
    assert again.status_code == 429 and "Try again in" in again.json()["detail"]
    assert client.get("/demo/reset").json()["available_in_seconds"] > 500
