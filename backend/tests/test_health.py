from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_integrations():
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert set(body["integrations"]) == {"Database", "Claude", "Channel3", "PayPal"}
