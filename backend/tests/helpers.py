from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.seed import seed

client = TestClient(app)


def login_as(name: str) -> dict[str, str]:
    """Seed the demo scenario and return auth headers for the named persona."""
    with SessionLocal() as db:
        seed(db)
    persona = next(p for p in client.get("/auth/personas").json() if p["name"] == name)
    token = client.post("/auth/demo-login", json={"user_id": persona["id"]}).json()["token"]
    return {"Authorization": f"Bearer {token}"}
