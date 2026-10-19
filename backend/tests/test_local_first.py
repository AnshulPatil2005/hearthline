from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from app.db import SessionLocal
from app.models import Business, LocalOffer, Purchase, RegistryItem, ReopenCampaign, User
from tests.helpers import client, login_as
from tests.test_shopping import fakes, fund  # noqa: F401  (the fake Shopper picks homedepot.com boots, $129.99)


def store(*, price: str, category: str = "clothing", city: str = "Sablewood", verified: bool = True, campaign=None):
    """Rosa's Sablewood Mercantile, selling one item."""
    login_as("Rosa Delgado")
    with SessionLocal() as db:
        rosa = db.query(User).filter_by(name="Rosa Delgado").one()
        b = Business(
            owner_user_id=rosa.id,
            name="Sablewood Mercantile",
            slug="sablewood-mercantile",
            kind="retail",
            address_line="15 Main St",
            city=city,
            state="CA",
            license_number="SBW-BL-10077",
            payout_email="rosa.delgado@business.example.com",
            verification="verified" if verified else "pending",
        )
        db.add(b)
        db.flush()
        if campaign:
            db.add(
                ReopenCampaign(
                    business_id=b.id,
                    goal_amount=D(1000),
                    reopen_by=datetime.now(UTC) + timedelta(days=10),
                    status=campaign,
                )
            )
        db.add(LocalOffer(business_id=b.id, title="Steel-toe work boots", category=category, unit_price=D(price)))
        db.commit()
        return b.id


def purchase_for(item_name: str) -> Purchase:
    with SessionLocal() as db:
        item = db.query(RegistryItem).filter_by(name=item_name).one()
        return db.query(Purchase).filter_by(registry_item_id=item.id).order_by(Purchase.id.desc()).first()


def test_a_reopened_local_store_wins_within_15_percent(fakes):  # noqa: F811
    business_id = store(price="139.00", campaign="reopened")  # 7% above the Shopper's online pick
    fund("Steel-toe work boots")
    p = purchase_for("Steel-toe work boots")
    assert (p.status, p.retailer, p.local_business_id, p.unit_price) == (
        "paid",
        "Sablewood Mercantile",
        business_id,
        D("139.00"),
    )
    assert "Bought locally" in p.ai_reasoning and "7% more than homedepot.com ($129.99)" in p.ai_reasoning
    assert next(c for c in p.policy_checks if c["rule"] == "known_retailer")["passed"]
    payments, _ = fakes[-1]
    assert payments[0][:2] == ("rosa.delgado@business.example.com", D("139.00"))  # paid to the store's PayPal
    assert p.candidates_considered == 4  # three online offers and the local one
    assert client.get("/households/me/fund", headers=login_as("Elena Rivera")).json()["spent"] == "139.00"


def test_online_wins_when_the_local_price_is_too_high(fakes):  # noqa: F811
    store(price="159.00")  # 22% more than $129.99
    fund("Steel-toe work boots")
    p = purchase_for("Steel-toe work boots")
    assert p.local_business_id is None and p.retailer == "homedepot.com"
    assert "Sablewood Mercantile was checked first, but its price was 22% above online" in p.ai_reasoning


def test_compared_with_what_the_shopper_would_buy_not_the_cheapest_listing(fakes):  # noqa: F811
    store(price="120.00")  # 35% above the cheapest listing ($89), but below the Shopper's pick ($129.99)
    fund("Steel-toe work boots")
    p = purchase_for("Steel-toe work boots")
    assert p.retailer == "Sablewood Mercantile"
    assert "no more than the best online match ($129.99 at homedepot.com)" in p.ai_reasoning


@pytest.mark.parametrize(
    "kwargs",
    [
        {"campaign": "live"},  # still closed, raising money to reopen
        {"verified": False},
        {"city": "Henderson"},  # not the family's town
        {"category": "bedding"},  # not what the family needs
    ],
)
def test_only_open_verified_stores_in_town_selling_the_thing_count(fakes, kwargs):  # noqa: F811
    store(price="90.00", **kwargs)
    fund("Steel-toe work boots")
    assert purchase_for("Steel-toe work boots").local_business_id is None


def test_with_nothing_online_the_local_store_still_serves(fakes, monkeypatch):  # noqa: F811
    from app.agents import shopper

    monkeypatch.setattr(shopper, "find_candidates", lambda query, budget: [])
    store(price="135.00")
    fund("Steel-toe work boots")
    p = purchase_for("Steel-toe work boots")
    assert (p.status, p.retailer) == ("paid", "Sablewood Mercantile")


def test_the_store_sees_the_order_and_delivers_it(fakes):  # noqa: F811
    store(price="99.00")
    fund("Steel-toe work boots")
    rosa = login_as("Rosa Delgado")
    orders = client.get("/businesses/me/orders", headers=rosa).json()
    assert [(o["title"], o["total"], o["status"]) for o in orders] == [("Steel-toe work boots", "99.00", "paid")]
    assert (orders[0]["family"], orders[0]["contact_name"]) == ("Rivera household", "Elena Rivera")
    delivered = client.post(f"/businesses/me/orders/{orders[0]['id']}/delivered", headers=rosa).json()
    assert delivered[0]["status"] == "delivered"
    with SessionLocal() as db:
        assert db.query(RegistryItem).filter_by(name="Steel-toe work boots").one().status == "delivered"
    assert client.post(f"/businesses/me/orders/{orders[0]['id']}/delivered", headers=rosa).status_code == 409
    assert (
        client.post(f"/businesses/me/orders/{orders[0]['id']}/delivered", headers=login_as("Luis Moreno")).status_code
        == 404
    )


def test_the_store_keeps_its_catalog(fakes):  # noqa: F811
    store(price="99.00")
    rosa = login_as("Rosa Delgado")
    shop = client.post(
        "/businesses/me/offers", json={"title": "Wool blanket", "category": "bedding", "unit_price": "45"}, headers=rosa
    ).json()
    assert shop["open"] is True and [o["title"] for o in shop["offers"]] == ["Steel-toe work boots", "Wool blanket"]
    blanket = shop["offers"][1]["id"]
    shop = client.patch(f"/businesses/me/offers/{blanket}", json={"available": False}, headers=rosa).json()
    assert shop["offers"][1]["available"] is False
    shop = client.delete(f"/businesses/me/offers/{blanket}", headers=rosa).json()
    assert len(shop["offers"]) == 1
    assert client.get("/businesses/me/offers", headers=login_as("Luis Moreno")).status_code == 404  # no business


def test_web_listings_that_dont_fit_are_not_the_price_yardstick(fakes, monkeypatch):  # noqa: F811
    from app.agents import shopper
    from app.agents.shopper import Candidate, ShopperChoice

    insoles = [Candidate(f"i{n}", "Steel toe insoles", "walmart.com", D("40.00"), f"https://x/i{n}") for n in range(3)]
    monkeypatch.setattr(shopper, "find_candidates", lambda query, budget: insoles)
    monkeypatch.setattr(
        shopper,
        "choose",
        lambda need, note, qty, budget, cands: ShopperChoice(
            choice=0 if cands[0].retailer == "Sablewood Mercantile" else -1, reasoning="", confidence=0.9
        ),
    )
    store(price="129.00")  # over 1.5x the insoles' $40, but nothing online is a pair of boots
    fund("Steel-toe work boots")
    p = purchase_for("Steel-toe work boots")
    assert (p.status, p.retailer) == ("paid", "Sablewood Mercantile")
    assert next(c for c in p.policy_checks if c["rule"] == "price_sanity")["passed"]
