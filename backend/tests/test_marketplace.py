"""The agent marketplace: the Shopper asks local stores' pricing agents for quotes over MCP (in-process in tests),
counters once, and buys from the best within its limit. The stores' agents price at list here unless a test sets
them up (conftest)."""

from decimal import Decimal as D

from fastapi.testclient import TestClient

from app import ai, store_mcp
from app.agents import store as store_agent
from app.db import SessionLocal
from app.models import Business, LocalOffer, MarketQuote, Purchase, RegistryItem, User
from tests.helpers import client, login_as
from tests.test_shopping import fakes, fund  # noqa: F401  (online: homedepot.com boots at $129.99; the item is $139)

BOOTS = "Steel-toe work boots"


def shop(name: str, slug: str, *, price: str, floor: str, stock: int = 3, note: str = "") -> int:
    """A verified, open store in Sablewood selling boots, owned by Rosa (one owner is enough for these tests)."""
    login_as("Rosa Delgado")
    with SessionLocal() as db:
        rosa = db.query(User).filter_by(name="Rosa Delgado").one()
        b = Business(
            owner_user_id=rosa.id,
            name=name,
            slug=slug,
            kind="retail",
            address_line="1 Main St",
            city="Sablewood",
            state="CA",
            license_number=f"SBW-{slug}",
            payout_email=f"{slug}@business.example.com",
            verification="verified",
            agent_note=note,
        )
        db.add(b)
        db.flush()
        db.add(
            LocalOffer(
                business_id=b.id,
                title=f"{name} steel-toe boots",
                category="clothing",
                unit_price=D(price),
                floor_price=D(floor),
                stock=stock,
            )
        )
        db.commit()
        return b.id


def bought() -> Purchase:
    with SessionLocal() as db:
        item = db.query(RegistryItem).filter_by(name=BOOTS).one()
        p = db.query(Purchase).filter_by(registry_item_id=item.id).order_by(Purchase.id.desc()).first()
        db.expunge(p)
        return p


def quotes() -> dict[str, MarketQuote]:
    with SessionLocal() as db:
        found = {q.business.slug: q for q in db.query(MarketQuote).all()}
        for q in found.values():
            db.expunge(q)
        return found


def test_two_stores_quote_and_the_cheaper_one_within_the_limit_wins(fakes):  # noqa: F811
    shop("Sablewood Mercantile", "mercantile", price="129.00", floor="112.00")
    hardware = shop("Juniper Hardware", "hardware", price="124.00", floor="112.00", stock=2)
    fund(BOOTS)
    p = bought()
    assert (p.status, p.retailer, p.local_business_id, p.unit_price) == ("paid", "Juniper Hardware", hardware, D("124"))
    assert "Juniper Hardware quoted $124.00 each. Sablewood Mercantile offered $129.00" in p.ai_reasoning
    payments, _ = fakes[-1]
    assert payments[0][:2] == ("hardware@business.example.com", D("124.00"))  # the winning store's PayPal account
    q = quotes()
    assert (q["hardware"].status, q["hardware"].purchase_id, q["mercantile"].status) == ("accepted", p.id, "declined")
    with SessionLocal() as db:
        assert db.query(LocalOffer).filter_by(business_id=hardware).one().stock == 1  # the sale reserved the stock
    who = [m["from"] for m in p.negotiation]
    assert who.count("Hearthline's Shopper") >= 3 and "Juniper Hardware" in who and "Sablewood Mercantile" in who


def test_the_shopper_counters_once_and_the_store_accepts_above_its_floor(fakes):  # noqa: F811
    shop("Sablewood Mercantile", "mercantile", price="150.00", floor="120.00")
    fund(BOOTS)  # $139 given: above the list price's reach, the Shopper counters at $139
    p = bought()
    assert (p.status, p.retailer, p.unit_price) == ("paid", "Sablewood Mercantile", D("139.00"))
    assert "agreed to $139.00 each (list $150.00) after a counter-offer" in p.ai_reasoning
    counter = next(m for m in p.negotiation if m["from"] == "Hearthline's Shopper" and m["unit_price"])
    assert counter["unit_price"] == "139.00" and "that's what donors gave for this item" in counter["text"]
    assert quotes()["mercantile"].status == "accepted"


def test_a_store_that_cant_meet_the_limit_loses_to_online(fakes):  # noqa: F811
    shop("Sablewood Mercantile", "mercantile", price="170.00", floor="160.00")
    fund(BOOTS)
    p = bought()
    assert (p.local_business_id, p.retailer) == (None, "homedepot.com")
    assert "Local stores were asked first, but none could meet $139.00 each" in p.ai_reasoning
    final = [m for m in p.negotiation if m["from"] == "Sablewood Mercantile"][-1]
    assert final["unit_price"] == "160.00"  # its floor, and no lower
    assert quotes()["mercantile"].status == "declined"


def test_a_store_without_enough_stock_isnt_asked(fakes):  # noqa: F811
    shop("Sablewood Mercantile", "mercantile", price="100.00", floor="90.00", stock=0)
    fund(BOOTS)
    p = bought()
    assert p.retailer == "homedepot.com" and p.negotiation == [] and quotes() == {}


def test_the_store_agents_price_within_the_owners_rules(monkeypatch):
    def says(price, message="ok"):
        class Answer:
            unit_price = price

        Answer.message = message
        return lambda *a, **k: Answer()

    real = store_agent.ai
    monkeypatch.setattr(
        store_agent,
        "ai",
        type("AI", (), {"parse": staticmethod(says(50.0)), "text_part": real.text_part, "AIError": ai.AIError}),
    )
    low = store_agent.opening(
        store="S",
        owner_note="",
        item="Boots",
        need="boots",
        list_price=D("129"),
        floor=D("112"),
        quantity=1,
        delivery_days=1,
        competing=D("75"),
    )
    assert (low.unit_price, low.by_ai) == (D("112.00"), True)  # the AI's $50 is held to the floor
    monkeypatch.setattr(store_agent.ai, "parse", staticmethod(says(500.0)))
    high = store_agent.opening(
        store="S",
        owner_note="",
        item="Boots",
        need="boots",
        list_price=D("129"),
        floor=D("112"),
        quantity=1,
        delivery_days=1,
        competing=None,
    )
    assert high.unit_price == D("129.00")  # and to the list price
    answer, accepted = store_agent.reply_to_counter(
        store="S", owner_note="", item="Boots", counter=D("100"), floor=D("112"), current=D("129")
    )
    assert (answer.unit_price, accepted) == (D("112.00"), False)


def test_the_store_agents_endpoint_answers_hearthlines_shopper_only():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    assert client.post("/stores/mcp", json={}).status_code == 401  # the real mount, without the token
    inner = Starlette(routes=[Route("/mcp", lambda request: PlainTextResponse("ok"), methods=["POST"])])
    guarded = TestClient(store_mcp._RequireToken(inner))
    assert guarded.post("/mcp", headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = guarded.post("/mcp", headers={"Authorization": f"Bearer {store_mcp.internal_token()}"})
    assert ok.text == "ok"  # the Shopper's token passes; the MCP app (started with the API) answers it


def test_the_owner_sets_lowest_prices_stock_and_their_agents_instructions():
    shop("Sablewood Mercantile", "mercantile", price="129.00", floor="112.00")
    rosa = login_as("Rosa Delgado")
    shop_view = client.put("/businesses/me/agent", json={"note": "Best price for fire families"}, headers=rosa)
    assert shop_view.status_code == 200 and shop_view.json()["agent_note"] == "Best price for fire families"
    offer = shop_view.json()["offers"][0]
    too_low = client.patch(f"/businesses/me/offers/{offer['id']}", json={"floor_price": "9999"}, headers=rosa)
    assert too_low.status_code == 422
    updated = client.patch(
        f"/businesses/me/offers/{offer['id']}", json={"stock": 7, "floor_price": "100"}, headers=rosa
    )
    changed = next(o for o in updated.json()["offers"] if o["id"] == offer["id"])
    assert (changed["stock"], changed["floor_price"]) == (7, "100.00")
