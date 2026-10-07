from decimal import Decimal
from types import SimpleNamespace as NS

from app.agents.valuation import choose_price


def product(pid, title, *prices, availability="InStock", condition="new"):
    offers = [
        NS(price=NS(price=p), availability=availability, condition=condition, url=f"https://x/{pid}", domain="shop.com")
        for p in prices
    ]
    return NS(id=pid, title=title, offers=offers)


def test_median_of_cheapest_offers_ignores_parts_and_out_of_stock():
    products = [
        product("a", "Grey 3-seat sofa", 900, 950),
        product("b", "Linen sofa", 1200),
        product("c", "Velvet sofa", 600),
        product("d", "Sofa replacement cushion cover", 40),  # a part, not the item
        product("e", "Designer sofa", 9000, availability="OutOfStock"),
    ]
    v = choose_price(products)
    assert v.unit_price == Decimal("900.00")
    assert (v.price_low, v.price_high) == (Decimal("600.00"), Decimal("1200.00"))
    assert v.product_id == "a"
    assert v.offers_considered == 3


def test_no_usable_offers():
    assert choose_price([product("x", "Lamp replacement lens", 5)]) is None
    assert choose_price([]) is None
