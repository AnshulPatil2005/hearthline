"""Point the app at a throwaway database before anything imports app.db: SQLite by default, or the Postgres in
TEST_DATABASE_URL (what Render runs; every table is dropped and recreated, so never point it at real data)."""

import os
import tempfile
from functools import cache
from pathlib import Path

_db = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{_db}"

import pytest  # noqa: E402
from sqlalchemy import String, event  # noqa: E402
from sqlalchemy import inspect as sa_inspect  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

import app.models  # noqa: E402,F401
from app.db import Base, engine  # noqa: E402


@cache
def _string_columns(mapper) -> list[tuple[str, int]]:
    return [
        (prop.key, col.type.length)
        for prop in mapper.column_attrs
        for col in prop.columns
        if isinstance(col.type, String) and col.type.length
    ]


@event.listens_for(Session, "before_flush")
def _strings_fit_their_columns(session, flush_context, instances):
    """SQLite ignores VARCHAR lengths; Postgres, which production runs, rejects a value that doesn't fit (a 43-character
    PayPal account id once broke Log in with PayPal there). Fail the same way in tests."""
    for obj in (*session.new, *session.dirty):
        mapper = sa_inspect(obj).mapper
        for key, length in _string_columns(mapper):
            value = obj.__dict__.get(key)
            if isinstance(value, str) and len(value) > length:
                raise ValueError(
                    f"{mapper.class_.__name__}.{key} is {len(value)} characters; the column holds {length}"
                )


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


@pytest.fixture(autouse=True)
def paypal_reporting(monkeypatch):
    """PayPal Transaction Search through APIMatic's SDK, with the network replaced by a stub transport (the real
    client and request pipeline still run). Defaults: a $50,000 balance and no transactions; tests set routes."""
    from app.paypal import reporting
    from tests.paypal_stub import (
        BALANCES_PATH,
        TRANSACTIONS_PATH,
        RoutingTransport,
        balances_body,
        json_response,
        stub_client,
        transactions_body,
    )

    transport = RoutingTransport()
    transport.routes[BALANCES_PATH] = json_response(200, balances_body("50000.00"))
    transport.routes[TRANSACTIONS_PATH] = json_response(200, transactions_body([], refreshed="2099-01-01T00:00:00Z"))
    monkeypatch.setattr(reporting, "_client", stub_client(transport))
    return transport
