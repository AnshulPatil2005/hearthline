from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from app import paypal_connect, trust
from app.config import get_settings
from app.db import SessionLocal
from app.models import AuditEvent, Contractor, Household, PayPalLink, User
from app.paypal import identity
from tests.helpers import client, login_as

# Log in with PayPal's user ids are 43 characters (the end of the user_id URL), longer than a 13-character payer id.
ELENA_ID = "ElenaPayPalUserId_xxxxxxxxxxxxxxxxxxxxxxxxx"


@pytest.fixture
def paypal(monkeypatch):
    """PayPal credentials are set and the code exchange is faked: `people` maps a code to who signed in."""
    s = get_settings()
    monkeypatch.setattr(s, "paypal_client_id", "CLIENT-ID")
    monkeypatch.setattr(s, "paypal_client_secret", "SECRET")
    monkeypatch.setattr(s, "paypal_connect_return_url", None)  # the web app's own /connect/paypal
    people = {
        "code-elena": identity.PayPalPerson(ELENA_ID, "elena.r@personal.example.com", "Elena Rivera", True),
        "code-unverified": identity.PayPalPerson("PAYER-X", "new.account@personal.example.com", "E. Rivera", False),
        "code-dana": identity.PayPalPerson("PAYER-DANA", "dana@okafor.example.com", "Dana Okafor", True),
    }
    monkeypatch.setattr(identity, "exchange", lambda code: people[code])
    return people


def state_for(headers) -> str:
    url = client.post("/paypal/connect/start", headers=headers).json()["authorize_url"]
    return parse_qs(urlparse(url).query)["state"][0]


def test_the_sign_in_link_goes_to_paypal_with_our_return_page(paypal):
    elena = login_as("Elena Rivera")
    url = urlparse(client.post("/paypal/connect/start", headers=elena).json()["authorize_url"])
    q = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert (url.netloc, url.path) == ("www.sandbox.paypal.com", "/signin/authorize")
    assert q["client_id"] == "CLIENT-ID" and q["response_type"] == "code"
    assert "https://uri.paypal.com/services/paypalattributes" in q["scope"].split()
    assert q["redirect_uri"] == f"{get_settings().web_url}/connect/paypal"
    with SessionLocal() as db:
        elena_id = db.query(User).filter_by(name="Elena Rivera").one().id
    assert jwt.decode(q["state"], get_settings().secret_key, algorithms=["HS256"])["sub"] == str(elena_id)


def test_connecting_makes_the_paypal_account_where_cash_aid_goes(paypal):
    elena = login_as("Elena Rivera")
    before = client.get("/paypal/connect", headers=elena).json()
    assert before["connected"] is False and before["receives"][0]["what"] == "cash_aid"

    r = client.post("/paypal/connect/finish", json={"code": "code-elena", "state": state_for(elena)}, headers=elena)
    assert r.status_code == 200
    body = r.json()
    assert (body["connected"], body["email"], body["verified_account"]) == (True, "elena.r@personal.example.com", True)
    assert body["receives"] == [{"what": "cash_aid", "current": "el•••••@personal.example.com"}]
    with SessionLocal() as db:
        home = db.query(User).filter_by(name="Elena Rivera").one().household
        assert home.payout_email == "elena.r@personal.example.com"
        event = db.query(AuditEvent).filter_by(action="paypal.connected").one()
        assert event.data["payer_id"] == ELENA_ID
        assert event.data["changed"][0]["to"] == "el•••••@personal.example.com"
        assert "elena.r@" not in str(event.data)  # addresses are masked in the log


def test_a_state_from_someone_else_or_too_old_is_refused(paypal):
    elena, dana = login_as("Elena Rivera"), login_as("Dana Okafor")
    stolen = client.post("/paypal/connect/finish", json={"code": "code-dana", "state": state_for(elena)}, headers=dana)
    assert stolen.status_code == 400 and "someone else" in stolen.json()["detail"]

    with SessionLocal() as db:
        elena_id = db.query(User).filter_by(name="Elena Rivera").one().id
    old = jwt.encode(
        {"sub": str(elena_id), "purpose": "paypal_connect", "exp": datetime.now(UTC) - timedelta(minutes=1)},
        get_settings().secret_key,
        algorithm="HS256",
    )
    late = client.post("/paypal/connect/finish", json={"code": "code-elena", "state": old}, headers=elena)
    assert late.status_code == 400 and "too long" in late.json()["detail"]
    with SessionLocal() as db:
        assert db.query(PayPalLink).count() == 0


def test_contractor_milestones_follow_the_connected_account(paypal):
    dana = login_as("Dana Okafor")
    r = client.post("/paypal/connect/finish", json={"code": "code-dana", "state": state_for(dana)}, headers=dana)
    assert r.json()["receives"][0]["what"] == "milestone_payments"
    with SessionLocal() as db:
        user = db.query(User).filter_by(name="Dana Okafor").one()
        assert db.query(Contractor).filter_by(user_id=user.id).one().payout_email == "dana@okafor.example.com"


def test_donors_have_nothing_to_connect(paypal):
    marcus = login_as("Marcus Chen")
    assert client.get("/paypal/connect", headers=marcus).json()["receives"] == []
    assert client.post("/paypal/connect/start", headers=marcus).status_code == 409


def test_sentinel_notes_an_account_paypal_has_not_verified(paypal):
    elena = login_as("Elena Rivera")
    client.post("/paypal/connect/finish", json={"code": "code-unverified", "state": state_for(elena)}, headers=elena)
    with SessionLocal() as db:
        home = db.query(Household).filter_by(payout_email="new.account@personal.example.com").one()
        names = [f.code for f in trust.sentinel_flags(db, home)]
    assert "payout_account_unverified" in names


def test_userinfo_shapes():
    person = identity.person_from(
        {
            "user_id": "https://www.paypal.com/webapps/auth/identity/user/abc",
            "name": "Elena Rivera",
            "payer_id": "PAYER1",
            "verified_account": "true",
            "emails": [{"value": "old@x.example", "primary": False}, {"value": "main@x.example", "primary": True}],
        }
    )
    assert (person.payer_id, person.email, person.verified) == ("PAYER1", "main@x.example", True)
    bare = identity.person_from({"user_id": "https://x/user/XYZ", "given_name": "A", "family_name": "B"})
    assert (bare.payer_id, bare.email, bare.name, bare.verified) == ("XYZ", None, "A B", False)
    assert paypal_connect.mask("ab@x.example") == "ab•@x.example"


def test_a_configured_return_url_is_what_paypal_gets(paypal, monkeypatch):
    """PayPal only saves public https return URLs, so local runs register a placeholder (see .env.example)."""
    monkeypatch.setattr(get_settings(), "paypal_connect_return_url", "https://example.com/connect/paypal")
    url = client.post("/paypal/connect/start", headers=login_as("Elena Rivera")).json()["authorize_url"]
    assert parse_qs(urlparse(url).query)["redirect_uri"] == ["https://example.com/connect/paypal"]
