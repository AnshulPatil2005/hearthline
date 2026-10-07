from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.seed import seed

client = TestClient(app)


def seeded():
    with SessionLocal() as db:
        seed(db)


def test_personas_cover_every_role():
    seeded()
    personas = client.get("/auth/personas").json()
    assert {p["role"] for p in personas} == {
        "household",
        "donor",
        "contractor",
        "reviewer",
        "supervisor",
        "org_admin",
        "business",
    }
    household = next(p for p in personas if p["role"] == "household")
    assert household["household_id"] is not None


def test_demo_login_then_me():
    seeded()
    elena = next(p for p in client.get("/auth/personas").json() if p["name"] == "Elena Rivera")
    token = client.post("/auth/demo-login", json={"user_id": elena["id"]}).json()["token"]
    me = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "elena.rivera@demo.hearthline.app"


def test_me_rejects_missing_and_bad_tokens():
    assert client.get("/me").status_code == 401
    assert client.get("/me", headers={"Authorization": "Bearer not-a-token"}).status_code == 401


def test_demo_login_unknown_user():
    assert client.post("/auth/demo-login", json={"user_id": 9999}).status_code == 404
