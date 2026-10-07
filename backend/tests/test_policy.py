from decimal import Decimal as D

from app.policy import Proposal, evaluate

OK = dict(
    item_funded=D("139"),
    available_funds=D("500"),
    spent_today=D("0"),
    allowed_retailers={"homedepot.com"},
    ship_to_verified=True,
)


def proposal(**kw):
    base = dict(
        total=D("129.99"),
        category="clothing",
        retailer="homedepot.com",
        unit_price=D("129.99"),
        comparable_median=D("120"),
        ai_confidence=0.9,
    )
    return Proposal(**(base | kw))


def failed(decision):
    return {c.rule for c in decision.checks if not c.passed}


def test_small_purchase_is_allowed_without_approval():
    d = evaluate(proposal(), **OK)
    assert d.allowed and not d.needs_approval and failed(d) == set()


def test_big_or_unsure_purchases_need_approval():
    big = evaluate(
        proposal(total=D("450"), unit_price=D("225"), comparable_median=D("220")), **(OK | {"item_funded": D("498")})
    )
    assert big.allowed and big.needs_approval
    unsure = evaluate(proposal(ai_confidence=0.4), **OK)
    assert unsure.allowed and unsure.needs_approval


def test_each_rule_can_block():
    assert failed(evaluate(proposal(retailer="sketchy.shop"), **OK)) == {"known_retailer"}
    outlier = evaluate(proposal(unit_price=D("250"), total=D("250")), **(OK | {"item_funded": D("300")}))
    assert failed(outlier) == {"price_sanity"}
    assert failed(evaluate(proposal(), **(OK | {"available_funds": D("50")}))) == {"funds_available"}
    assert failed(evaluate(proposal(), **(OK | {"item_funded": D("100")}))) == {"within_item_funding"}
    assert failed(evaluate(proposal(), **(OK | {"spent_today": D("2400")}))) == {"daily_limit"}
    assert failed(evaluate(proposal(category="gift_card"), **OK)) == {"category_allowed"}
    assert failed(evaluate(proposal(), **(OK | {"ship_to_verified": False}))) == {"ships_to_verified_address"}
    over = evaluate(
        proposal(total=D("1200"), unit_price=D("1200"), comparable_median=D("1200")),
        **(OK | {"item_funded": D("1200"), "available_funds": D("5000")}),
    )
    assert failed(over) == {"per_item_limit"}
