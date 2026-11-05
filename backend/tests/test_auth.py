from app.db import SessionLocal
from app.seed import seed
from tests.helpers import client


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


def test_production_refuses_the_development_secret():
    import pytest
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(environment="production", _env_file=None)
    assert Settings(environment="production", secret_key="x" * 40, _env_file=None).secret_key == "x" * 40
    assert Settings(_env_file=None).environment == "development"  # local runs keep the default


def test_only_a_sign_in_token_signs_in():
    """The PayPal-connect state is signed with the same key but carries its own purpose: it can't be a login."""
    from datetime import UTC, datetime, timedelta

    import jwt

    from app.config import get_settings

    seeded()
    elena = next(p for p in client.get("/auth/personas").json() if p["name"] == "Elena Rivera")
    exp = datetime.now(UTC) + timedelta(minutes=10)
    key = get_settings().secret_key
    state = jwt.encode({"sub": str(elena["id"]), "purpose": "paypal_connect", "exp": exp}, key, algorithm="HS256")
    assert client.get("/me", headers={"Authorization": f"Bearer {state}"}).status_code == 401
    older = jwt.encode({"sub": str(elena["id"]), "exp": exp}, key, algorithm="HS256")  # issued before purposes
    assert client.get("/me", headers={"Authorization": f"Bearer {older}"}).status_code == 200


def test_live_paypal_only_on_purpose():
    import pytest
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match="sandbox"):
        Settings(paypal_environment="live", _env_file=None)
    assert Settings(paypal_environment="live", allow_live_paypal=True, _env_file=None).paypal_environment == "live"
