"""Point the app at a throwaway database before anything imports app.db: SQLite by default, or the Postgres in
TEST_DATABASE_URL (what Render runs; every table is dropped and recreated, so never point it at real data)."""

import os
import tempfile
from pathlib import Path

_db = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db}"

import pytest  # noqa: E402

import app.models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402


@pytest.fixture(autouse=True)
def no_background_shopping(monkeypatch):
    """Funding an item normally starts the Shopper in a background thread with real Channel3 and AI
    calls. Tests must never do that; test_shopping opts back in with an inline, faked Shopper."""
    from app import shopping

    monkeypatch.setattr(shopping, "start_auto_shop", lambda item_id: None)


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture(autouse=True)
def no_live_price_history(monkeypatch):
    """The gouging guard asks Channel3 for price history; tests never do. test_gouging fakes histories."""
    from app import gouging

    monkeypatch.setattr(gouging, "_channel3_history", lambda product_id, days: [])
    monkeypatch.setattr(gouging, "_start_tracking", lambda product_id: None)


@pytest.fixture(autouse=True)
def no_live_tracking(monkeypatch):
    """Shipping a purchase adds tracking to donors' PayPal payments; tests record the calls instead."""
    from app.paypal import tracking

    calls = []
    monkeypatch.setattr(
        tracking, "add", lambda order_id, capture_id, number, carrier: calls.append((order_id, capture_id, number))
    )
    return calls
